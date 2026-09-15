// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  applyAgentTextStreamEvent,
  applyAgentToolStreamEvent,
  mergeAgentToolInvocations,
} from "@/lib/agent-message-codec";
import {
  canSubmitAgentPrompt,
  getAgentQualityWarnings,
  mergeStreamingAgentMessage,
  shouldRollbackOptimisticAgentMessages,
} from "@/lib/agent-panel-state";
import {
  getAgentToolDisplayCategory,
  getAgentToolLabelKey,
  getAgentToolName,
  getVisibleCompletedTools,
  isToolError,
  isToolFailure,
  REGISTERED_AGENT_TOOL_NAMES,
  shouldShowTimelineContinuationStatus,
} from "@/lib/agent-tool-display";
import type {
  AgentChatMessage,
  AgentTimelinePart,
  AgentToolInvocation,
} from "@/types/api";

function tool(
  name: string,
  state: AgentToolInvocation["state"],
  overrides: Partial<AgentToolInvocation> = {},
): AgentToolInvocation {
  return {
    id: `call-${name}`,
    type: `tool-${name}`,
    title: name,
    state,
    ...overrides,
  };
}

const registeredTools = [
  ...readFileSync(
    new URL("../../backend/app/services/agent/contracts.py", import.meta.url),
    "utf8",
  ).matchAll(/AgentToolSpec\(\s*"([^"]+)"/g),
].map((match) => match[1]);

describe("incremental Agent messages", () => {
  it("appends text around tool groups in their visible order", () => {
    let message: AgentChatMessage = {
      id: "assistant-streaming",
      role: "assistant",
      text: "",
      timeline: [],
      tools: [],
    };
    for (const delta of ["先读取岗位", "要求。"]) {
      message = applyAgentTextStreamEvent(message, {
        delta,
        timelinePartId: "timeline-text-1",
      });
    }
    message = applyAgentToolStreamEvent(message, {
      timelinePartId: "timeline-tool-1",
      tool: tool("web_fetch", "input-available", { id: "call-fetch" }),
    });
    message = applyAgentTextStreamEvent(message, {
      delta: "改写完成。",
      timelinePartId: "timeline-text-3",
    });
    expect(message.text).toBe("先读取岗位要求。改写完成。");
    expect(message.timeline).toEqual([
      { id: "timeline-text-1", type: "text", text: "先读取岗位要求。" },
      { id: "timeline-tool-1", type: "tool_group", toolIds: ["call-fetch"] },
      { id: "timeline-text-3", type: "text", text: "改写完成。" },
    ]);
  });

  it("reconciles repeated events and late snapshots without regressing terminal tools or first-seen order", () => {
    const url = "https://example.com/job";
    const completed = tool("web_fetch", "output-available", {
      input: { url },
      completedAt: "2026-07-26T10:00:00Z",
      output: { sourceId: "source-public-job", url },
    });
    let message: AgentChatMessage = {
      id: "assistant-message",
      role: "assistant",
      text: "",
      tools: [],
    };
    for (const invocation of [
      tool("web_fetch", "input-streaming", { input: { url } }),
      tool("web_fetch", "input-available", { input: { url } }),
      completed,
      completed,
    ]) {
      message = applyAgentToolStreamEvent(message, { tool: invocation });
    }
    expect(message.tools).toHaveLength(1);
    expect(message.tools?.[0]).toMatchObject(completed);
    message = applyAgentToolStreamEvent(message, {
      tool: tool("edit_execute", "input-streaming"),
    });
    const reconciled = mergeAgentToolInvocations(message.tools, [
      tool("edit_execute", "output-available", { output: { editCount: 2 } }),
      tool("web_fetch", "input-available", { input: { url } }),
    ]);
    expect(reconciled.map(({ id }) => id)).toEqual([
      "call-web_fetch",
      "call-edit_execute",
    ]);
    expect(reconciled[0]).toMatchObject(completed);
    expect(reconciled[1].output).toEqual({ editCount: 2 });
  });

  it("appends new streaming messages and replaces an overlapping persisted frame", () => {
    const history = [{ id: "assistant-1", text: "persisted final" }];
    expect(
      mergeStreamingAgentMessage(history, {
        id: "assistant-2",
        text: "streaming",
      }).map(({ id }) => id),
    ).toEqual(["assistant-1", "assistant-2"]);
    expect(
      mergeStreamingAgentMessage(history, {
        id: "assistant-1",
        text: "last streamed frame",
      }),
    ).toEqual([{ id: "assistant-1", text: "last streamed frame" }]);
    expect(mergeStreamingAgentMessage(history, null)).toBe(history);
  });

  it.each([
    [false, false, true],
    [true, false, true],
    [true, true, false],
  ])(
    "rolls back replacement=%s accepted=%s only when unaccepted",
    (replaceSessionBeforeSend, runAccepted, expected) => {
      expect(
        shouldRollbackOptimisticAgentMessages({
          replaceSessionBeforeSend,
          runAccepted,
        }),
      ).toBe(expected);
    },
  );
});

describe("Agent tool presentation", () => {
  it("covers exactly the backend tool registry", () => {
    expect([...REGISTERED_AGENT_TOOL_NAMES].sort()).toEqual(
      [...registeredTools].sort(),
    );
  });
  it.each(registeredTools)(
    "provides the backend name and all phase labels for %s",
    (name) => {
      const invocation = tool(name, "input-streaming");
      expect(getAgentToolName(invocation)).toBe(name);
      for (const phase of ["running", "complete", "error"] as const)
        expect(getAgentToolLabelKey(invocation, phase)).toMatch(/^agentTool/);
    },
  );
  it.each([
    [
      "web_search",
      "search-job-reference",
      { query: "frontend engineer job description" },
    ],
    ["web_fetch", "fetch-job-reference", { url: "https://example.com/job" }],
    ["edit_execute", "generate-draft", undefined],
    ["future_tool", "processing", undefined],
  ] as const)("categorizes %s as %s", (name, category, input) => {
    expect(
      getAgentToolDisplayCategory(tool(name, "input-streaming", { input })),
    ).toBe(category);
  });
  it("uses generic completion wording for unknown tools", () => {
    expect(
      getAgentToolLabelKey(tool("future_tool", "input-streaming"), "complete"),
    ).toBe("agentToolProcessingDone");
  });
  it.each(["output-error", "output-denied", "output-available"] as const)(
    "distinguishes terminal state %s",
    (state) => {
      expect(isToolError(state)).toBe(state !== "output-available");
    },
  );
  it.each([
    [0, 1, true],
    [1, 0, false],
  ] as const)(
    "recognizes structured edit rejection %s accepted / %s rejected",
    (editCount, rejectedEditCount, failed) => {
      expect(
        isToolFailure(
          tool("edit_execute", "output-available", {
            output: { editCount, rejectedEditCount },
          }),
        ),
      ).toBe(failed);
    },
  );
  it.each([
    {
      name: "completed tool in live stream",
      streaming: true,
      running: false,
      text: false,
      expected: true,
    },
    {
      name: "running tool",
      streaming: true,
      running: true,
      text: false,
      expected: false,
    },
    {
      name: "completed message",
      streaming: false,
      running: false,
      text: false,
      expected: false,
    },
    {
      name: "resumed text output",
      streaming: true,
      running: false,
      text: true,
      expected: false,
    },
  ])(
    "shows continuation only after $name",
    ({ streaming, running, text, expected }) => {
      const invocation = tool(
        "web_fetch",
        running ? "input-available" : "output-available",
      );
      const parts: AgentTimelinePart[] = [
        { id: "timeline-tool-1", type: "tool_group", toolIds: [invocation.id] },
      ];
      if (text)
        parts.push({ id: "timeline-text-2", type: "text", text: "改写完成。" });
      expect(
        shouldShowTimelineContinuationStatus(parts, [invocation], streaming),
      ).toBe(expected);
    },
  );
  it.each([
    {
      name: "an older success cannot hide a newer failure",
      states: ["output-available", "output-error"],
      expected: [0, 1],
    },
    {
      name: "all distinct successful invocations remain auditable",
      states: ["output-available", "output-available", "output-available"],
      expected: [0, 1, 2],
      distinctUrls: true,
    },
    {
      name: "later success hides recovered failures but retains all successes",
      states: [
        "output-available",
        "output-error",
        "output-available",
        "output-available",
        "output-error",
        "output-available",
        "output-available",
      ],
      expected: [0, 2, 3, 5, 6],
    },
    {
      name: "unrecovered failures collapse to the latest failure",
      states: ["output-error", "output-error"],
      expected: [1],
    },
  ] satisfies Array<{
    name: string;
    states: AgentToolInvocation["state"][];
    expected: number[];
    distinctUrls?: boolean;
  }>)("$name", ({ states, expected, distinctUrls }) => {
    const invocations = states.map((state, index) =>
      tool("web_fetch", state, {
        id: `fetch-${index}`,
        input: { url: `https://example.com/job${distinctUrls ? index : ""}` },
        ...(state === "output-error"
          ? { errorText: "Latest fetch failed" }
          : {}),
      }),
    );
    expect(getVisibleCompletedTools(invocations).map(({ id }) => id)).toEqual(
      expected.map((index) => `fetch-${index}`),
    );
  });
});

describe("Agent submission gates and diagnostics", () => {
  it.each([
    {
      hasConfiguredModel: true,
      isRequestBusy: false,
      isSessionReady: true,
      isSubmitting: false,
      allowed: true,
    },
    {
      hasConfiguredModel: true,
      isRequestBusy: false,
      isSessionReady: false,
      isSubmitting: false,
      allowed: false,
    },
    {
      hasConfiguredModel: true,
      isRequestBusy: true,
      isSessionReady: true,
      isSubmitting: false,
      allowed: false,
    },
    {
      hasConfiguredModel: false,
      isRequestBusy: false,
      isSessionReady: true,
      isSubmitting: false,
      allowed: false,
    },
    {
      hasConfiguredModel: true,
      isRequestBusy: false,
      isSessionReady: true,
      isSubmitting: true,
      allowed: false,
    },
  ])(
    "requires a configured, ready, idle composer: %j",
    ({ allowed, ...state }) =>
      expect(canSubmitAgentPrompt(state)).toBe(allowed),
  );
  it("only surfaces completed-tool warnings and deduplicates by code and target", () => {
    const warnings = [
      {
        code: "target_requirements_not_covered",
        severity: "warning",
        target: "resume",
      },
      {
        code: "unsupported_edit_claim",
        severity: "warning",
        target: "basic.summary",
      },
      { code: "mixed_resume_languages", severity: "warning", target: "resume" },
    ];
    expect(
      getAgentQualityWarnings([
        tool("edit_execute", "output-available", {
          output: { qualityIssues: [...warnings, warnings[2]] },
        }),
        tool("edit_execute", "output-error", {
          output: {
            qualityIssues: [
              {
                code: "must-not-surface",
                severity: "warning",
                target: "resume",
              },
            ],
          },
        }),
      ]),
    ).toEqual(warnings.map(({ code, target }) => ({ code, target })));
  });
});
