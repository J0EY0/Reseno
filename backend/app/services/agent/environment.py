from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.schemas.agent import (
    AgentChatRequest,
    AgentResumeEditSuggestion,
    AgentSource,
    AgentToolInvocation,
    AgentTransactionState,
)
from app.services.llm import LlmRequestError, LlmToolCall, LlmWebSource

from .adapters import AttachmentToolAdapter, WebToolAdapter
from .contracts import (
    agent_tool_spec,
    agent_tool_specs_for_request,
)
from .draft import DraftEditEngine, DraftTransaction
from .localization import agent_text
from .privacy import resume_hidden_terms, sanitize_agent_text, sanitize_agent_value
from .runtime.context import AgentRuntimeContext


@dataclass(frozen=True)
class ToolEffect:
    """One model-visible observation and its draft effect."""

    invocation: AgentToolInvocation
    observation: dict[str, Any]
    edits: tuple[AgentResumeEditSuggestion, ...]
    transaction_state: AgentTransactionState
    edits_changed: bool


@dataclass(frozen=True)
class EnvironmentResult:
    """Domain state returned when the loop closes the environment."""

    tools: tuple[AgentToolInvocation, ...]
    sources: tuple[AgentSource, ...]
    edits: tuple[AgentResumeEditSuggestion, ...]
    transaction_state: AgentTransactionState
    base_resume: dict[str, Any]


class ResumeToolEnvironment:
    """Execute one model-selected tool at a time behind a narrow seam."""

    @classmethod
    def open(
        cls,
        request: AgentChatRequest,
        *,
        include_web_tools: bool = True,
    ) -> ResumeToolEnvironment:
        return cls(request, include_web_tools=include_web_tools)

    def __init__(
        self,
        request: AgentChatRequest,
        *,
        include_web_tools: bool = True,
    ) -> None:
        self._request = request
        transaction = DraftTransaction.from_request(request)
        self._draft = DraftEditEngine.open(request, transaction)
        self._hidden_terms = resume_hidden_terms(self._draft.active_resume)
        self._attachments = AttachmentToolAdapter.open(
            request,
            hidden_terms=self._hidden_terms,
        )
        self._tool_specs = agent_tool_specs_for_request(
            request,
            include_web_tools=include_web_tools,
        )
        self._web = (
            WebToolAdapter.open(
                request,
                prompt=request.message.text.strip(),
                hidden_terms=self._hidden_terms,
            )
            if include_web_tools
            else None
        )
        self._provider_sources: dict[str, AgentSource] = {}
        self._tools: list[AgentToolInvocation] = []
        self._tool_call_results: dict[
            str,
            tuple[str, AgentToolInvocation, dict[str, Any]],
        ] = {}
        self._closed_result: EnvironmentResult | None = None

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return [spec.schema for spec in self._tool_specs]

    def executable_tool_calls(
        self,
        tool_calls: list[LlmToolCall],
    ) -> tuple[LlmToolCall, ...]:
        """Return calls that execute in this causal layer."""

        read_indexes, write_indexes = self._read_write_indexes(tool_calls)
        if not read_indexes or not write_indexes:
            return tuple(tool_calls)

        deferred_indexes = set(write_indexes)
        return tuple(
            tool_call
            for index, tool_call in enumerate(tool_calls)
            if index not in deferred_indexes
        )

    def record_sources(self, sources: list[LlmWebSource]) -> None:
        """Retain provider-hosted web sources without exposing provider details."""

        for source in sources:
            parsed_url = urlsplit(source.url)
            if parsed_url.scheme.casefold() not in {"http", "https"} or not (
                parsed_url.netloc
            ):
                continue
            title = sanitize_agent_text(
                source.title,
                hidden_terms=self._hidden_terms,
            )
            self._provider_sources[source.id] = AgentSource(
                id=source.id,
                title=title or source.url,
                sourceType="web",
                url=source.url,
                excerpt=(
                    sanitize_agent_text(
                        source.excerpt,
                        hidden_terms=self._hidden_terms,
                    )
                    or None
                ),
            )

    async def invoke(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> ToolEffect:
        """Execute one call without deciding whether the model loop should end."""

        if self._closed_result is not None:
            raise LlmRequestError(
                "Cannot invoke a tool after the environment is closed.",
            )

        revision_before = self._draft.revision
        invocation, observation = await self._execute(tool_call, runtime)
        return ToolEffect(
            invocation=invocation,
            observation=observation,
            edits=tuple(deepcopy(self._draft.edits)),
            transaction_state=self._draft.transaction_state,
            edits_changed=self._draft.revision != revision_before,
        )

    async def invoke_batch(
        self,
        tool_calls: list[LlmToolCall],
        runtime: AgentRuntimeContext,
    ) -> tuple[ToolEffect, ...]:
        """Execute one causal tool layer in the model's observation order."""

        read_indexes, write_indexes = self._read_write_indexes(tool_calls)
        causal_batch = bool(read_indexes and write_indexes)
        if not causal_batch and len(read_indexes) != len(tool_calls):
            sequential_effects: list[ToolEffect] = []
            for tool_call in tool_calls:
                sequential_effects.append(await self.invoke(tool_call, runtime))
            return tuple(sequential_effects)

        tool_start = len(self._tools)
        uncached_ids = {
            tool_call.id
            for tool_call in tool_calls
            if tool_call.id not in self._tool_call_results
        }
        tasks = {
            index: asyncio.create_task(self.invoke(tool_calls[index], runtime))
            for index in read_indexes
        }
        try:
            read_effects = await asyncio.gather(*tasks.values())
        except BaseException:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            raise

        effects_by_index = dict(zip(tasks, read_effects, strict=True))
        write_index_set = set(write_indexes)
        for index, tool_call in enumerate(tool_calls):
            if index in effects_by_index:
                continue
            effects_by_index[index] = (
                self._defer_write(tool_call)
                if index in write_index_set
                else await self.invoke(tool_call, runtime)
            )

        effects = tuple(effects_by_index[index] for index in range(len(tool_calls)))
        completed = {tool.id: tool for tool in self._tools[tool_start:]}
        self._tools[tool_start:] = [
            completed[tool_call.id]
            for tool_call in tool_calls
            if tool_call.id in completed and tool_call.id in uncached_ids
        ]
        return effects

    def _defer_write(self, tool_call: LlmToolCall) -> ToolEffect:
        revision_before = self._draft.revision
        cached = self._cached_tool_call_result(tool_call)
        if cached is None:
            started_at = self._tool_timestamp()
            invocation = AgentToolInvocation(
                id=tool_call.id,
                type=f"tool-{tool_call.name}",
                title=tool_call.name,
                state="output-available",
                input={"editCount": len(tool_call.arguments["edits"])},
                output={
                    "status": "not_executed",
                    "editCount": 0,
                    "reason": (
                        "Read-tool results from this response are now available. "
                        "Review them before deciding whether to generate a new "
                        "write."
                    ),
                },
                startedAt=started_at,
                completedAt=self._tool_timestamp(),
            )
            cached = (
                invocation,
                self._tool_result(invocation),
            )
        invocation, observation = cached
        return ToolEffect(
            invocation=invocation,
            observation=observation,
            edits=tuple(deepcopy(self._draft.edits)),
            transaction_state=self._draft.transaction_state,
            edits_changed=self._draft.revision != revision_before,
        )

    def _read_write_indexes(
        self,
        tool_calls: list[LlmToolCall],
    ) -> tuple[list[int], list[int]]:
        specs = [agent_tool_spec(tool_call.name) for tool_call in tool_calls]
        enabled_specs = [
            spec if spec in self._tool_specs else None for spec in specs
        ]
        read_indexes = [
            index
            for index, spec in enumerate(enabled_specs)
            if spec is not None and spec.mode == "read"
        ]
        write_indexes = [
            index
            for index, spec in enumerate(enabled_specs)
            if spec is not None and spec.mode == "write"
        ]
        return read_indexes, write_indexes

    def close(self, *, completed: bool) -> EnvironmentResult:
        """Commit or roll back the draft and return the environment's domain state."""

        if self._closed_result is not None:
            return deepcopy(self._closed_result)

        draft_result = self._draft.finalize(completed=completed)
        local_sources = self._web.sources(tuple(self._tools)) if self._web else ()
        sources = {source.id: source for source in local_sources}
        sources.update(self._provider_sources)
        self._closed_result = EnvironmentResult(
            tools=tuple(deepcopy(self._tools)),
            sources=tuple(sources.values()),
            edits=tuple(deepcopy(draft_result.edits)),
            transaction_state=draft_result.transaction_state,
            base_resume=deepcopy(draft_result.base_resume),
        )
        return deepcopy(self._closed_result)

    async def aclose(self) -> None:
        if self._web is not None:
            await self._web.close()

    async def _execute(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> tuple[AgentToolInvocation, dict[str, Any]]:
        cached = self._cached_tool_call_result(tool_call)
        if cached is not None:
            return cached

        started_at = self._tool_timestamp()
        spec = agent_tool_spec(tool_call.name)
        if spec is None:
            return self._record_tool_call(
                tool_call,
                self._unknown_tool(tool_call),
                started_at,
            )
        if spec not in self._tool_specs:
            return self._record_tool_call(
                tool_call,
                self._blocked_tool_call(tool_call),
                started_at,
            )

        if tool_call.name == "attachment_read":
            attachment_result = await self._attachments.invoke(
                tool_call.arguments.get("attachmentId"),
                tool_call.arguments.get("offset", 0),
                runtime,
            )
            if attachment_result.evidence_ref and attachment_result.material_text:
                self._draft.add_material(
                    attachment_result.evidence_ref,
                    attachment_result.material_text,
                )
            tool = attachment_result.invocation.model_copy(
                update={"id": tool_call.id},
            )
        elif spec.mode == "read":
            if self._web is None:
                raise LlmRequestError("Local web tools are not available this turn.")
            tool = await self._web.invoke(tool_call, runtime)
        else:
            tool = self._run_edit_execute(tool_call)
        return self._record_tool_call(tool_call, tool, started_at)

    def _blocked_tool_call(
        self,
        tool_call: LlmToolCall,
    ) -> AgentToolInvocation:
        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            output={"blocked": True},
            errorText=agent_text(
                self._request.locale,
                "error.tool_blocked_suggest_only",
            ),
        )

    def _unknown_tool(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            errorText=agent_text(
                self._request.locale,
                "error.unknown_tool",
                name=tool_call.name,
            ),
        )

    @staticmethod
    def _tool_timestamp() -> str:
        timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")
        return timestamp.replace("+00:00", "Z")

    @staticmethod
    def _tool_call_fingerprint(tool_call: LlmToolCall) -> str:
        return json.dumps(
            {"name": tool_call.name, "arguments": tool_call.arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _cached_tool_call_result(
        self,
        tool_call: LlmToolCall,
    ) -> tuple[AgentToolInvocation, dict[str, Any]] | None:
        if not tool_call.id.strip():
            raise LlmRequestError("Model tool call id must be non-empty.")

        cached = self._tool_call_results.get(tool_call.id)
        if cached is None:
            return None
        fingerprint, tool, observation = cached
        if fingerprint != self._tool_call_fingerprint(tool_call):
            raise LlmRequestError(
                "Model reused a tool call id with different arguments.",
            )
        return deepcopy(tool), deepcopy(observation)

    def _record_tool_call(
        self,
        tool_call: LlmToolCall,
        tool: AgentToolInvocation,
        started_at: str,
    ) -> tuple[AgentToolInvocation, dict[str, Any]]:
        completed_tool = tool.model_copy(
            update={
                "started_at": started_at,
                "completed_at": self._tool_timestamp(),
            },
        )
        observation = self._tool_result(completed_tool)
        self._tools.append(completed_tool)
        self._tool_call_results[tool_call.id] = (
            self._tool_call_fingerprint(tool_call),
            deepcopy(completed_tool),
            deepcopy(observation),
        )
        return completed_tool, observation

    def _tool_result(self, tool: AgentToolInvocation) -> dict[str, Any]:
        output = sanitize_agent_value(
            tool.output,
            hidden_terms=self._hidden_terms,
        )
        if (
            tool.title == "edit_execute"
            and tool.state == "output-available"
            and isinstance(output, dict)
            and isinstance(observations := output.get("observations"), list)
        ):
            # The invocation retains complete before/after values for review and
            # persistence. The model already has its operation arguments, so the
            # next turn only needs confirmation of what the engine accepted.
            output = {
                "status": "accepted",
                "editCount": output.get("editCount", len(observations)),
            }
        return {
            "title": tool.title,
            "state": tool.state,
            "output": output,
            "errorText": sanitize_agent_value(
                tool.error_text,
                hidden_terms=self._hidden_terms,
            ),
        }

    def _run_edit_execute(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        batch = self._draft.execute(tool_call.arguments.get("edits"))
        if not batch.accepted:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-edit_execute",
                title="edit_execute",
                state="output-error",
                input=tool_call.arguments,
                output=batch.observation,
                errorText=agent_text(
                    self._request.locale,
                    "error.edit_execute_rejected_detailed",
                ),
            )

        edit_count = batch.observation["editCount"]
        observations = batch.observation["observations"]
        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-edit_execute",
            title="edit_execute",
            state="output-available",
            input={"editCount": edit_count},
            output={
                "editCount": edit_count,
                "observations": observations,
            },
        )
