import type { AgentToolInvocation } from "@/types/api";

export function isToolRunning(state: AgentToolInvocation["state"]) {
  return (
    state === "approval-requested" ||
    state === "input-available" ||
    state === "input-streaming"
  );
}

function isToolError(state: AgentToolInvocation["state"]) {
  return state === "output-error" || state === "output-denied";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function toolName(tool: AgentToolInvocation) {
  return `${tool.type} ${tool.title}`.toLowerCase();
}

function toolPurpose(tool: AgentToolInvocation) {
  return isRecord(tool.input) && typeof tool.input.purpose === "string"
    ? tool.input.purpose
    : "";
}

function toolDisplayKey(tool: AgentToolInvocation) {
  const name = toolName(tool);
  const purpose = toolPurpose(tool);

  if (name.includes("web_fetch")) {
    return `web_fetch:${purpose}`;
  }
  if (name.includes("web_search")) {
    return `web_search:${purpose}`;
  }
  if (name.includes("resume") && name.includes("analysis")) {
    return "resume_analysis";
  }
  if (name.includes("material_extract")) {
    return "material_extract";
  }
  if (name.includes("edit_plan")) {
    return "edit_plan";
  }
  if (name.includes("edit_execute")) {
    return "edit_execute";
  }

  return `${tool.type}:${tool.title}`;
}

function toolRecoveryKey(tool: AgentToolInvocation) {
  const name = toolName(tool);
  const purpose = toolPurpose(tool);

  if (
    (name.includes("web_fetch") || name.includes("web_search")) &&
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
    if (isToolError(tool.state)) {
      latestErrorByRecoveryKey.set(recoveryKey, index);
      return;
    }

    latestSuccessByDisplayKey.set(toolDisplayKey(tool), index);
    successfulRecoveryKeys.add(recoveryKey);
  });

  return completedTools.filter((tool, index) => {
    const recoveryKey = toolRecoveryKey(tool);
    if (isToolError(tool.state)) {
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
