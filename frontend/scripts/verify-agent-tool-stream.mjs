import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { evaluateTypeScript } from "./typescript-module.mjs";

const frontendRoot = new URL("..", import.meta.url).pathname;
const repositoryRoot = join(frontendRoot, "..");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function loadTypeScriptModule(path) {
  const source = await readFile(path, "utf8");

  return evaluateTypeScript(source);
}

function tool(name, state, overrides = {}) {
  return {
    id: overrides.id ?? `call-${name}`,
    type: `tool-${name}`,
    title: name,
    state,
    ...overrides,
  };
}

const messageCodec = await loadTypeScriptModule(
  join(frontendRoot, "src", "lib", "agent-message-codec.ts"),
);
const toolDisplay = await loadTypeScriptModule(
  join(frontendRoot, "src", "lib", "agent-tool-display.ts"),
);

{
  let message = {
    id: "assistant-streaming",
    role: "assistant",
    text: "",
    timeline: [],
    tools: [],
  };
  message = messageCodec.applyAgentTextStreamEvent(message, {
    delta: "先读取岗位",
    timelinePartId: "timeline-text-1",
  });
  message = messageCodec.applyAgentTextStreamEvent(message, {
    delta: "要求。",
    timelinePartId: "timeline-text-1",
  });
  message = messageCodec.applyAgentToolStreamEvent(message, {
    timelinePartId: "timeline-tool-1",
    tool: tool("web_fetch", "input-available", { id: "call-fetch" }),
  });
  message = messageCodec.applyAgentTextStreamEvent(message, {
    delta: "改写完成。",
    timelinePartId: "timeline-text-3",
  });

  assert(
    message.text === "先读取岗位要求。改写完成。",
    "Text deltas must append without receiving an accumulated message snapshot.",
  );
  assert(
    message.timeline.map((part) => part.type).join(",") ===
      "text,tool_group,text" &&
      message.timeline[0].text === "先读取岗位要求。" &&
      message.timeline[1].toolIds.join(",") === "call-fetch" &&
      message.timeline[2].text === "改写完成。",
    "Incremental text and tool events must preserve the visible timeline order.",
  );
}

{
  const fetchUrl = "https://example.com/job";
  let message = {
    id: "assistant-message",
    role: "assistant",
    text: "",
    tools: [],
  };
  const started = tool("web_fetch", "input-streaming", {
    input: { url: fetchUrl },
  });
  const progressed = tool("web_fetch", "input-available", {
    input: { url: fetchUrl },
  });
  const completed = tool("web_fetch", "output-available", {
    input: { url: fetchUrl },
    completedAt: "2026-07-26T10:00:00Z",
    output: { sourceId: "source-public-job", url: fetchUrl },
  });

  message = messageCodec.applyAgentToolStreamEvent(message, { tool: started });
  message = messageCodec.applyAgentToolStreamEvent(message, {
    tool: progressed,
  });
  message = messageCodec.applyAgentToolStreamEvent(message, {
    tool: completed,
  });
  message = messageCodec.applyAgentToolStreamEvent(message, {
    tool: completed,
  });

  assert(
    message.tools.length === 1,
    "Repeated tool events must update one invocation instead of duplicating it.",
  );
  assert(
    message.tools[0].state === "output-available" &&
      message.tools[0].output.url === fetchUrl,
    "tool_done must preserve the terminal state and output.",
  );

  message = messageCodec.applyAgentToolStreamEvent(message, {
    tool: tool("edit_execute", "input-streaming"),
  });
  const reconciled = messageCodec.mergeAgentToolInvocations(message.tools, [
    tool("edit_execute", "output-available", { output: { editCount: 2 } }),
    tool("web_fetch", "input-available", { input: { url: fetchUrl } }),
  ]);

  assert(
    reconciled.map((item) => item.id).join(",") ===
      "call-web_fetch,call-edit_execute",
    "A snapshot must reconcile by id without changing first-seen order.",
  );
  assert(
    reconciled[0].state === "output-available",
    "A late snapshot must not regress a completed invocation.",
  );
  assert(
    reconciled[1].output.editCount === 2,
    "A full snapshot must still reconcile the latest tool output.",
  );
}

{
  const registrySource = await readFile(
    join(repositoryRoot, "backend", "app", "services", "agent", "contracts.py"),
    "utf8",
  );
  const backendToolNames = Array.from(
    registrySource.matchAll(/AgentToolSpec\(\s*"([^"]+)"/g),
    (match) => match[1],
  );
  const frontendToolNames = Array.from(toolDisplay.REGISTERED_AGENT_TOOL_NAMES);

  assert(
    JSON.stringify([...frontendToolNames].sort()) ===
      JSON.stringify([...backendToolNames].sort()),
    "Frontend tool display metadata must cover every registered backend tool.",
  );

  for (const name of backendToolNames) {
    const invocation = tool(name, "input-streaming");
    assert(
      toolDisplay.getAgentToolName(invocation) === name,
      `Tool ${name} must resolve from its backend invocation type.`,
    );
    for (const phase of ["running", "complete", "error"]) {
      assert(
        toolDisplay
          .getAgentToolLabelKey(invocation, phase)
          .startsWith("agentTool"),
        `Tool ${name} must have a ${phase} label fallback.`,
      );
    }
  }

  assert(
    toolDisplay.getAgentToolDisplayCategory(
      tool("web_search", "input-streaming", {
        input: { query: "frontend engineer job description" },
      }),
    ) === "search-job-reference",
    "Web searches must use a status distinct from fetching a selected page.",
  );
  assert(
    toolDisplay.getAgentToolDisplayCategory(
      tool("web_fetch", "input-streaming", {
        input: { url: "https://example.com/job" },
      }),
    ) === "fetch-job-reference",
    "JD fetches must retain their dedicated user-facing status.",
  );
  assert(
    toolDisplay.getAgentToolDisplayCategory(
      tool("edit_execute", "input-streaming"),
    ) === "generate-draft",
    "The general resume mutation tool must use the draft-generation status.",
  );
  assert(
    toolDisplay.isToolError(tool("edit_execute", "output-error").state) &&
      toolDisplay.isToolError(tool("edit_execute", "output-denied").state) &&
      !toolDisplay.isToolError(tool("edit_execute", "output-available").state),
    "Terminal tool failures must remain distinguishable from successful actions.",
  );
  assert(
    toolDisplay.isToolFailure(
      tool("edit_execute", "output-available", {
        output: { editCount: 0, rejectedEditCount: 1 },
      }),
    ) &&
      !toolDisplay.isToolFailure(
        tool("edit_execute", "output-available", {
          output: { editCount: 1, rejectedEditCount: 0 },
        }),
      ),
    "Structured edit rejection must be displayed as a failed tool outcome.",
  );

  const completedTool = tool("web_fetch", "output-available");
  const runningTool = tool("web_fetch", "input-available");
  const completedToolPart = [
    { id: "timeline-tool-1", type: "tool_group", toolIds: [completedTool.id] },
  ];
  assert(
    toolDisplay.shouldShowTimelineContinuationStatus(
      completedToolPart,
      [completedTool],
      true,
    ),
    "A live stream paused after a completed tool must show continuation feedback.",
  );
  assert(
    !toolDisplay.shouldShowTimelineContinuationStatus(
      completedToolPart,
      [runningTool],
      true,
    ) &&
      !toolDisplay.shouldShowTimelineContinuationStatus(
        completedToolPart,
        [completedTool],
        false,
      ) &&
      !toolDisplay.shouldShowTimelineContinuationStatus(
        [
          ...completedToolPart,
          { id: "timeline-text-2", type: "text", text: "改写完成。" },
        ],
        [completedTool],
        true,
      ),
    "Running tools, completed messages, and active text output must not duplicate the continuation shimmer.",
  );

  assert(
    toolDisplay
      .getVisibleCompletedTools([
        tool("web_fetch", "output-available", {
          id: "fetch-success-before-failure",
          input: { url: "https://example.com/job" },
        }),
        tool("web_fetch", "output-error", {
          id: "fetch-latest-failure",
          input: { url: "https://example.com/job" },
          errorText: "Latest fetch failed",
        }),
      ])
      .map((item) => item.id)
      .join(",") === "fetch-success-before-failure,fetch-latest-failure",
    "An older success must not hide the latest failure in chronological recovery order.",
  );

  assert(
    toolDisplay
      .getVisibleCompletedTools([
        tool("web_fetch", "output-available", {
          id: "fetch-success-1",
          input: { url: "https://example.com/job-1" },
        }),
        tool("web_fetch", "output-available", {
          id: "fetch-success-2",
          input: { url: "https://example.com/job-2" },
        }),
        tool("web_fetch", "output-available", {
          id: "fetch-success-3",
          input: { url: "https://example.com/job-3" },
        }),
      ])
      .map((item) => item.id)
      .join(",") === "fetch-success-1,fetch-success-2,fetch-success-3",
    "Distinct successful invocation ids must remain visible for an auditable call count.",
  );

  const unknownTool = tool("future_tool", "input-streaming");
  assert(
    toolDisplay.getAgentToolDisplayCategory(unknownTool) === "processing" &&
      toolDisplay.getAgentToolLabelKey(unknownTool, "complete") ===
        "agentToolProcessingDone",
    "Unknown future tools must use the generic processing fallback.",
  );
}

console.log("Agent tool stream and display metadata checks passed.");
