import type {
  ModelSettingsRouteData,
  ResumeGalleryRouteData,
  TemplateRouteData,
  TrashRouteData,
} from "@/lib/workspace-route-data";
import type { WorkspaceView } from "@/types/resume";

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

export type WorkspaceLateralRouteHandoffState<
  View extends WorkspaceView = WorkspaceView,
> = {
  [CurrentView in View]: {
    kind: "workspace-lateral-handoff";
    token: string;
    view: CurrentView;
  };
}[View];

export interface WorkspaceLateralRouteResolution<
  View extends WorkspaceView,
> {
  data: WorkspaceLateralRouteDataMap[View] | null;
  shouldScrubHistory: boolean;
  tokenToDelete: string | null;
}

const routeDataByToken = new Map<string, PreparedWorkspaceRoute>();
const latestRouteDataByView = new Map<
  WorkspaceView,
  PreparedWorkspaceRoute
>();
const routeMemorySession = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2)}`;
let nextRouteToken = 0;

function hasValidTheme(data: Record<string, unknown>) {
  return (
    data.theme === undefined ||
    data.theme === "light" ||
    data.theme === "dark" ||
    data.theme === "system"
  );
}

function hasTemplateRouteData(data: Record<string, unknown>) {
  return (
    hasValidTheme(data) &&
    typeof data.defaultTemplateId === "string" &&
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

function getLatestRouteData<View extends WorkspaceView>(view: View) {
  const prepared = latestRouteDataByView.get(view);
  return prepared?.view === view &&
    hasWorkspaceLateralRouteData(view, prepared.data)
    ? (prepared.data as WorkspaceLateralRouteDataMap[View])
    : null;
}

/** Keeps one last-known-good snapshot per view for the current auth session. */
export function rememberWorkspaceLateralRoute<View extends WorkspaceView>(
  prepared: PreparedWorkspaceRoute<View>,
) {
  if (!hasWorkspaceLateralRouteData(prepared.view, prepared.data)) {
    return;
  }

  latestRouteDataByView.set(
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
  nextRouteToken += 1;
  const token = `${routeMemorySession}-${nextRouteToken}`;
  routeDataByToken.set(token, prepared as PreparedWorkspaceRoute);

  return {
    kind: "workspace-lateral-handoff",
    token,
    view: prepared.view,
  } as WorkspaceLateralRouteHandoffState<View>;
}

export function resolveWorkspaceLateralRoute<
  View extends WorkspaceView,
>(state: unknown, view: View): WorkspaceLateralRouteResolution<View> {
  if (!state || typeof state !== "object") {
    return {
      data: getLatestRouteData(view),
      shouldScrubHistory: false,
      tokenToDelete: null,
    };
  }

  const candidate = state as {
    data?: unknown;
    kind?: unknown;
    token?: unknown;
    view?: unknown;
  };
  if (candidate.kind !== "workspace-lateral-handoff") {
    return {
      data: getLatestRouteData(view),
      shouldScrubHistory: false,
      tokenToDelete: null,
    };
  }

  const token = typeof candidate.token === "string" ? candidate.token : null;
  const prepared = token ? routeDataByToken.get(token) : null;
  if (
    candidate.view === view &&
    !Object.prototype.hasOwnProperty.call(candidate, "data") &&
    prepared?.view === view &&
    hasWorkspaceLateralRouteData(view, prepared.data)
  ) {
    rememberWorkspaceLateralRoute(prepared);
    return {
      data: prepared.data as WorkspaceLateralRouteDataMap[View],
      shouldScrubHistory: true,
      tokenToDelete: token,
    };
  }

  return {
    data: getLatestRouteData(view),
    shouldScrubHistory: true,
    tokenToDelete: token,
  };
}

export function deleteWorkspaceLateralRouteHandoff(token: string | null) {
  if (token) {
    routeDataByToken.delete(token);
  }
}

export function clearWorkspaceLateralRouteMemory() {
  routeDataByToken.clear();
  latestRouteDataByView.clear();
}
