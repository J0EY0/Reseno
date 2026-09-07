import type { AgentTimelinePart, AgentToolInvocation } from "@/types/api";

type AgentToolDisplayPhase = "running" | "complete" | "error";

type AgentToolDisplayCategory =
  | "fetch-job-reference"
  | "search-job-reference"
  | "read-material"
  | "generate-draft"
  | "processing";

interface AgentToolDisplayMetadata {
  category: AgentToolDisplayCategory;
}

/**
 * Frontend presentation metadata for every backend-registered Agent tool.
 * Keep names here exact; callers should not infer behavior with substring
 * checks because new tools must receive an explicit, reviewable category.
 */
const AGENT_TOOL_DISPLAY_METADATA = {
  web_search: { category: "search-job-reference" },
  web_fetch: { category: "fetch-job-reference" },
  attachment_read: { category: "read-material" },
  edit_execute: { category: "generate-draft" },
} as const satisfies Record<string, AgentToolDisplayMetadata>;

type AgentToolName = keyof typeof AGENT_TOOL_DISPLAY_METADATA;

export const REGISTERED_AGENT_TOOL_NAMES = Object.freeze(
  Object.keys(AGENT_TOOL_DISPLAY_METADATA) as AgentToolName[],
);

const AGENT_TOOL_LABEL_KEYS = {
  "fetch-job-reference": {
    running: "agentToolFetchingJob",
    complete: "agentToolFetchingJobDone",
    error: "agentToolFetchingJobFailed",
  },
  "search-job-reference": {
    running: "agentToolSearchingJob",
    complete: "agentToolSearchingJobDone",
    error: "agentToolSearchingJobFailed",
  },
  "read-material": {
    running: "agentToolExtractingMaterial",
    complete: "agentToolExtractingMaterialDone",
    error: "agentToolExtractingMaterialFailed",
  },
  "generate-draft": {
    running: "agentToolGeneratingDraft",
    complete: "agentToolGeneratingDraftDone",
    error: "agentToolGeneratingDraftFailed",
  },
  processing: {
    running: "agentToolProcessing",
    complete: "agentToolProcessingDone",
    error: "agentToolFailed",
  },
} as const satisfies Record<
  AgentToolDisplayCategory,
  Record<AgentToolDisplayPhase, string>
>;

type AgentToolLabelKey =
  (typeof AGENT_TOOL_LABEL_KEYS)[AgentToolDisplayCategory][AgentToolDisplayPhase];

export function isToolRunning(state: AgentToolInvocation["state"]) {
  return (
    state === "approval-requested" ||
    state === "input-available" ||
    state === "input-streaming"
  );
}

export function shouldShowTimelineContinuationStatus(
  parts: AgentTimelinePart[],
  tools: AgentToolInvocation[],
  isStreamingAssistant: boolean,
) {
  if (
    !isStreamingAssistant ||
    tools.some((tool) => isToolRunning(tool.state))
  ) {
    return false;
  }

  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index];
    if (part.type === "text" && part.text?.trim()) {
      return false;
    }
    if (part.type === "tool_group" && part.toolIds?.length) {
      return true;
    }
  }

  return false;
}

export function isToolError(state: AgentToolInvocation["state"]) {
  return state === "output-error" || state === "output-denied";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

/**
 * A tool can finish at the transport layer while rejecting its domain work.
 * Treat a structured rejected edit batch as a failure so stored timelines and
 * live stream events share the same user-facing outcome.
 */
export function isToolFailure(tool: AgentToolInvocation) {
  if (isToolError(tool.state)) {
    return true;
  }

  if (!isRecord(tool.output)) {
    return false;
  }

  const rejectedEditCount = tool.output.rejectedEditCount;
  return (
    typeof rejectedEditCount === "number" &&
    Number.isInteger(rejectedEditCount) &&
    rejectedEditCount > 0
  );
}

function isAgentToolName(value: string): value is AgentToolName {
  return Object.hasOwn(AGENT_TOOL_DISPLAY_METADATA, value);
}

export function getAgentToolName(tool: AgentToolInvocation) {
  const title = tool.title.trim();
  if (isAgentToolName(title)) {
    return title;
  }

  const type = tool.type.trim().replace(/^tool-/, "");
  return isAgentToolName(type) ? type : undefined;
}

export function getAgentToolDisplayCategory(
  tool: AgentToolInvocation,
): AgentToolDisplayCategory {
  const name = getAgentToolName(tool);
  if (!name) {
    return "processing";
  }

  return AGENT_TOOL_DISPLAY_METADATA[name].category;
}

export function getAgentToolLabelKey(
  tool: AgentToolInvocation,
  phase: AgentToolDisplayPhase,
): AgentToolLabelKey {
  return AGENT_TOOL_LABEL_KEYS[getAgentToolDisplayCategory(tool)][phase];
}

function toolDisplayKey(tool: AgentToolInvocation) {
  const name = getAgentToolName(tool);
  if (name) {
    return name;
  }

  return `${tool.type}:${tool.title}`;
}

function toolRecoveryKey(tool: AgentToolInvocation) {
  return toolDisplayKey(tool);
}

export function getVisibleCompletedTools(tools: AgentToolInvocation[]) {
  const completedTools = tools.filter((tool) => !isToolRunning(tool.state));
  const latestSuccessByRecoveryKey = new Map<string, number>();
  const latestErrorByRecoveryKey = new Map<string, number>();

  completedTools.forEach((tool, index) => {
    const recoveryKey = toolRecoveryKey(tool);
    if (isToolFailure(tool)) {
      latestErrorByRecoveryKey.set(recoveryKey, index);
      return;
    }

    latestSuccessByRecoveryKey.set(recoveryKey, index);
  });

  return completedTools.filter((tool, index) => {
    const recoveryKey = toolRecoveryKey(tool);
    if (isToolFailure(tool)) {
      const latestSuccess = latestSuccessByRecoveryKey.get(recoveryKey);
      return (
        (latestSuccess === undefined || latestSuccess < index) &&
        latestErrorByRecoveryKey.get(recoveryKey) === index
      );
    }

    return true;
  });
}

export function getVisibleToolIds(tools: AgentToolInvocation[]) {
  return new Set(getVisibleCompletedTools(tools).map((tool) => tool.id));
}
