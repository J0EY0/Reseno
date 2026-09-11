export const EDITOR_MIN_WIDTH = 372;
export const EDITOR_MAX_WIDTH = 560;
export const PREVIEW_MIN_WIDTH = 420;
export const AGENT_MIN_WIDTH = 300;
export const AGENT_MAX_WIDTH = 520;
export const DEFAULT_AGENT_WIDTH = 360;

const workspaceLayoutKey = "reseno-workspace-layout-v1";

export type WorkspaceLayoutPreference = {
  editorWidth?: number;
  agentWidth?: number;
  agentCollapsed?: boolean;
};

function resolveWidth(value: unknown, minimum: number, maximum: number) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(maximum, Math.max(minimum, value))
    : undefined;
}

function normalizePreference(value: unknown): WorkspaceLayoutPreference {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }

  const preference = value as WorkspaceLayoutPreference;
  const editorWidth = resolveWidth(
    preference.editorWidth,
    EDITOR_MIN_WIDTH,
    EDITOR_MAX_WIDTH,
  );
  const agentWidth = resolveWidth(
    preference.agentWidth,
    AGENT_MIN_WIDTH,
    AGENT_MAX_WIDTH,
  );

  return {
    ...(editorWidth === undefined ? {} : { editorWidth }),
    ...(agentWidth === undefined ? {} : { agentWidth }),
    ...(typeof preference.agentCollapsed === "boolean"
      ? { agentCollapsed: preference.agentCollapsed }
      : {}),
  };
}

export function getDefaultEditorWidth(containerWidth: number) {
  return Math.min(432, Math.max(EDITOR_MIN_WIDTH, 0.27 * containerWidth + 32));
}

export function readWorkspaceLayoutPreference(): WorkspaceLayoutPreference {
  try {
    return normalizePreference(
      JSON.parse(window.localStorage.getItem(workspaceLayoutKey) ?? "null"),
    );
  } catch {
    return {};
  }
}

export function writeWorkspaceLayoutPreference(
  patch: WorkspaceLayoutPreference,
) {
  try {
    window.localStorage.setItem(
      workspaceLayoutKey,
      JSON.stringify({
        ...readWorkspaceLayoutPreference(),
        ...normalizePreference(patch),
      }),
    );
  } catch {
    return;
  }
}

export function resolveWorkspaceWidths(
  containerWidth: number,
  preferences: WorkspaceLayoutPreference,
  agentExpanded: boolean,
) {
  const availableWidth = Math.max(
    containerWidth,
    EDITOR_MIN_WIDTH + PREVIEW_MIN_WIDTH + AGENT_MIN_WIDTH,
  );
  const preference = normalizePreference(preferences);
  const desiredEditorWidth =
    preference.editorWidth ?? getDefaultEditorWidth(containerWidth);
  const desiredAgentWidth = preference.agentWidth ?? DEFAULT_AGENT_WIDTH;
  const editorWidth = Math.min(
    desiredEditorWidth,
    availableWidth - PREVIEW_MIN_WIDTH - (agentExpanded ? AGENT_MIN_WIDTH : 0),
  );
  const agentMaxWidth = Math.max(
    AGENT_MIN_WIDTH,
    Math.min(AGENT_MAX_WIDTH, availableWidth - PREVIEW_MIN_WIDTH - editorWidth),
  );
  const agentWidth = agentExpanded
    ? Math.min(desiredAgentWidth, agentMaxWidth)
    : desiredAgentWidth;

  return {
    editorWidth,
    agentWidth,
    editorMaxWidth: Math.min(
      EDITOR_MAX_WIDTH,
      availableWidth - PREVIEW_MIN_WIDTH - (agentExpanded ? agentWidth : 0),
    ),
    agentMaxWidth,
  };
}
