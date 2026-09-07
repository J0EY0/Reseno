import type {
  ModelSettingsRouteData,
  ResumeGalleryRouteData,
  TemplateRouteData,
  TrashRouteData,
} from "@/lib/workspace-route-data";
import type { WorkspaceView } from "@/types/resume";
import {
  clearWorkspaceRouteHandoffs,
  createWorkspaceHandoffToken,
  readWorkspaceHandoffToken,
} from "@/lib/workspace-route-handoff";

export interface WorkspaceLateralRouteDataMap {
  models: ModelSettingsRouteData;
  resume: ResumeGalleryRouteData;
  settings: ModelSettingsRouteData;
  templates: TemplateRouteData;
  trash: TrashRouteData;
}

export type PreparedWorkspaceRoute<
  View extends WorkspaceView = WorkspaceView,
> = {
  [CurrentView in View]: {
    data: WorkspaceLateralRouteDataMap[CurrentView];
    view: CurrentView;
  };
}[View];

type WorkspaceLateralRouteHandoffState<
  View extends WorkspaceView = WorkspaceView,
> = {
  [CurrentView in View]: {
    kind: "workspace-lateral-handoff";
    token: string;
    view: CurrentView;
  };
}[View];

interface WorkspaceLateralRouteResolution<
  View extends WorkspaceView,
> {
  data: WorkspaceLateralRouteDataMap[View] | null;
  shouldScrubHistory: boolean;
  tokenToDelete: string | null;
}

const committedRouteDataByView = new Map<
  WorkspaceView,
  PreparedWorkspaceRoute
>();

function hasValidTheme(data: Record<string, unknown>) {
  return (
    data.theme === undefined ||
    data.theme === "light" ||
    data.theme === "dark" ||
    data.theme === "system"
  );
}

function hasTemplateRouteData(data: Record<string, unknown>) {
  const defaultTemplateIds = data.defaultTemplateIds;

  return (
    hasValidTheme(data) &&
    Boolean(defaultTemplateIds) &&
    typeof defaultTemplateIds === "object" &&
    typeof (defaultTemplateIds as Record<string, unknown>).zh === "string" &&
    typeof (defaultTemplateIds as Record<string, unknown>).en === "string" &&
    Array.isArray(data.customTemplates)
  );
}

function hasWorkspaceLateralRouteData(
  view: WorkspaceView,
  data: unknown,
) {
  if (!data || typeof data !== "object") {
    return false;
  }

  const candidate = data as Record<string, unknown>;
  switch (view) {
    case "resume":
      return hasTemplateRouteData(candidate) && Array.isArray(candidate.resumes);
    case "templates":
      return hasTemplateRouteData(candidate);
    case "trash":
      return (
        hasTemplateRouteData(candidate) &&
        Array.isArray(candidate.deletedResumes) &&
        Array.isArray(candidate.deletedTemplates)
      );
    case "models":
    case "settings":
      return (
        hasValidTheme(candidate) &&
        Array.isArray(candidate.modelConfigs) &&
        Boolean(candidate.agentSettings) &&
        typeof candidate.agentSettings === "object"
      );
  }
}

function getCommittedRouteData<View extends WorkspaceView>(view: View) {
  const prepared = committedRouteDataByView.get(view);
  return prepared?.view === view &&
    hasWorkspaceLateralRouteData(view, prepared.data)
    ? (prepared.data as WorkspaceLateralRouteDataMap[View])
    : null;
}

/** Keeps at most one committed snapshot for each of the five lateral views. */
export function rememberWorkspaceLateralRoute<View extends WorkspaceView>(
  prepared: PreparedWorkspaceRoute<View>,
) {
  if (!hasWorkspaceLateralRouteData(prepared.view, prepared.data)) {
    return;
  }

  committedRouteDataByView.set(
    prepared.view,
    prepared as PreparedWorkspaceRoute,
  );
}

export function createWorkspaceLateralRouteHandoff<
  View extends WorkspaceView,
>(
  prepared: PreparedWorkspaceRoute<View>,
): WorkspaceLateralRouteHandoffState<View> {
  rememberWorkspaceLateralRoute(prepared);
  const token = createWorkspaceHandoffToken(prepared);

  return {
    kind: "workspace-lateral-handoff",
    token,
    view: prepared.view,
  } as WorkspaceLateralRouteHandoffState<View>;
}

export function getWorkspaceLateralRouteHandoff(
  state: unknown,
): PreparedWorkspaceRoute | null {
  if (!state || typeof state !== "object") {
    return null;
  }

  const candidate = state as {
    kind?: unknown;
    token?: unknown;
    view?: unknown;
  };
  if (
    candidate.kind !== "workspace-lateral-handoff" ||
    typeof candidate.token !== "string" ||
    Object.prototype.hasOwnProperty.call(candidate, "data")
  ) {
    return null;
  }

  const prepared = readWorkspaceHandoffToken(candidate.token) as
    | PreparedWorkspaceRoute
    | undefined;
  return prepared &&
    prepared.view === candidate.view &&
    hasWorkspaceLateralRouteData(prepared.view, prepared.data)
    ? prepared
    : null;
}

export function resolveWorkspaceLateralRoute<
  View extends WorkspaceView,
>(state: unknown, view: View): WorkspaceLateralRouteResolution<View> {
  if (!state || typeof state !== "object") {
    return {
      data: getCommittedRouteData(view),
      shouldScrubHistory: false,
      tokenToDelete: null,
    };
  }

  const candidate = state as {
    kind?: unknown;
    token?: unknown;
  };
  if (candidate.kind !== "workspace-lateral-handoff") {
    return {
      data: getCommittedRouteData(view),
      shouldScrubHistory: false,
      tokenToDelete: null,
    };
  }

  const token = typeof candidate.token === "string" ? candidate.token : null;
  const prepared = getWorkspaceLateralRouteHandoff(state);
  if (prepared?.view === view) {
    rememberWorkspaceLateralRoute(prepared);
    return {
      data: prepared.data as WorkspaceLateralRouteDataMap[View],
      shouldScrubHistory: true,
      tokenToDelete: token,
    };
  }

  return {
    data: getCommittedRouteData(view),
    shouldScrubHistory: true,
    tokenToDelete: token,
  };
}

export function clearWorkspaceRouteMemory() {
  clearWorkspaceRouteHandoffs();
  committedRouteDataByView.clear();
}
