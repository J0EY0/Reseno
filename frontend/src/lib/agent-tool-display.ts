import type { AgentToolInvocation } from "@/types/api";

export type AgentToolDisplayPhase = "running" | "complete" | "error";

export type AgentToolDisplayCategory =
  | "fetch-job-reference"
  | "search-job-reference"
  | "analyze-resume"
  | "read-resume"
  | "extract-material"
  | "plan-edits"
  | "generate-draft"
  | "processing";

interface AgentToolDisplayMetadata {
  category: AgentToolDisplayCategory;
  purposeCategories?: Partial<Record<string, AgentToolDisplayCategory>>;
}

/**
 * Frontend presentation metadata for every backend-registered Agent tool.
 * Keep names here exact; callers should not infer behavior with substring
 * checks because new tools must receive an explicit, reviewable category.
 */
const AGENT_TOOL_DISPLAY_METADATA = {
  web_fetch: {
    category: "processing",
    purposeCategories: {
      jd: "fetch-job-reference",
    },
  },
  web_search: { category: "search-job-reference" },
  material_extract: { category: "extract-material" },
  resume_analysis: { category: "analyze-resume" },
  resume_lookup: { category: "read-resume" },
  draft_diff_summary: { category: "read-resume" },
  edit_plan: { category: "plan-edits" },
  edit_execute: { category: "generate-draft" },
  edit_move_item: { category: "generate-draft" },
  edit_split_item: { category: "generate-draft" },
  edit_merge_items: { category: "generate-draft" },
  skills_classify: { category: "generate-draft" },
  draft_rewrite: { category: "generate-draft" },
  finish: { category: "processing" },
} as const satisfies Record<string, AgentToolDisplayMetadata>;

export type AgentToolName = keyof typeof AGENT_TOOL_DISPLAY_METADATA;

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
  "analyze-resume": {
    running: "agentToolAnalyzingResume",
    complete: "agentToolAnalyzingResumeDone",
    error: "agentToolAnalyzingResumeFailed",
  },
  "read-resume": {
    running: "agentToolReadingResume",
    complete: "agentToolReadingResumeDone",
    error: "agentToolFailed",
  },
  "extract-material": {
    running: "agentToolExtractingMaterial",
    complete: "agentToolExtractingMaterialDone",
    error: "agentToolExtractingMaterialFailed",
  },
  "plan-edits": {
    running: "agentToolPlanningEdits",
    complete: "agentToolPlanningEditsDone",
    error: "agentToolPlanningEditsFailed",
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

export type AgentToolLabelKey =
  (typeof AGENT_TOOL_LABEL_KEYS)[AgentToolDisplayCategory][AgentToolDisplayPhase];

export function isToolRunning(state: AgentToolInvocation["state"]) {
  return (
    state === "approval-requested" ||
    state === "input-available" ||
    state === "input-streaming"
  );
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

function toolPurpose(tool: AgentToolInvocation) {
  return isRecord(tool.input) && typeof tool.input.purpose === "string"
    ? tool.input.purpose
    : "";
}

export function getAgentToolDisplayCategory(
  tool: AgentToolInvocation,
): AgentToolDisplayCategory {
  const name = getAgentToolName(tool);
  if (!name) {
    return "processing";
  }

  const metadata: AgentToolDisplayMetadata =
    AGENT_TOOL_DISPLAY_METADATA[name];
  return (
    metadata.purposeCategories?.[toolPurpose(tool)] ?? metadata.category
  );
}

export function getAgentToolLabelKey(
  tool: AgentToolInvocation,
  phase: AgentToolDisplayPhase,
): AgentToolLabelKey {
  return AGENT_TOOL_LABEL_KEYS[getAgentToolDisplayCategory(tool)][phase];
}

export function isAgentEditExecutionTool(tool: AgentToolInvocation) {
  return getAgentToolName(tool) === "edit_execute";
}

function toolDisplayKey(tool: AgentToolInvocation) {
  const name = getAgentToolName(tool);
  const purpose = toolPurpose(tool);

  if (name === "web_fetch") {
    return `web_fetch:${purpose}`;
  }
  if (name === "web_search") {
    return `web_search:${purpose}`;
  }
  if (name) {
    return name;
  }

  return `${tool.type}:${tool.title}`;
}

function toolRecoveryKey(tool: AgentToolInvocation) {
  const name = getAgentToolName(tool);
  const purpose = toolPurpose(tool);

  if (
    (name === "web_fetch" || name === "web_search") &&
    (purpose === "jd" || purpose === "target_context")
  ) {
    return "job_reference";
  }

  return toolDisplayKey(tool);
}

export function getVisibleCompletedTools(tools: AgentToolInvocation[]) {
  const completedTools = tools.filter((tool) => !isToolRunning(tool.state));
  const latestSuccessByDisplayKey = new Map<string, number>();
  const latestErrorByRecoveryKey = new Map<string, number>();
  const successfulRecoveryKeys = new Set<string>();

  completedTools.forEach((tool, index) => {
    const recoveryKey = toolRecoveryKey(tool);
    if (isToolFailure(tool)) {
      latestErrorByRecoveryKey.set(recoveryKey, index);
      return;
    }

    latestSuccessByDisplayKey.set(toolDisplayKey(tool), index);
    successfulRecoveryKeys.add(recoveryKey);
  });

  return completedTools.filter((tool, index) => {
    const recoveryKey = toolRecoveryKey(tool);
    if (isToolFailure(tool)) {
      return (
        !successfulRecoveryKeys.has(recoveryKey) &&
        latestErrorByRecoveryKey.get(recoveryKey) === index
      );
    }

    return latestSuccessByDisplayKey.get(toolDisplayKey(tool)) === index;
  });
}

export function getVisibleToolIds(tools: AgentToolInvocation[]) {
  return new Set(getVisibleCompletedTools(tools).map((tool) => tool.id));
}
