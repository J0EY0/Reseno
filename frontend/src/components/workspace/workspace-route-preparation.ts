import { isAbortError } from "@/lib/api-client";
import { isBuiltinTemplateId } from "@/lib/template-presets";
import {
  fetchResumeApi,
  fetchResumeVersionsApi,
  fetchWorkspaceRouteData,
} from "@/lib/workspace-api";
import type {
  LoadableWorkspaceRouteDataKind,
  PreparedResumeDetailRouteData,
  WorkspaceRouteDataResult,
  WorkspaceTemplateRouteData,
} from "@/lib/workspace-route-data";
import { loadDocumentCanvas } from "@/components/preview/document-canvas-loader";
import {
  loadResumeDetailWorkspacePage,
  loadWorkspacePreferencesProvider,
  loadTemplateDetailWorkspacePage,
  preloadWorkspaceRoute,
} from "@/components/workspace/workspace-route-loaders";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type { PreparedWorkspaceRoute } from "@/lib/workspace-route-memory";
import type { ResumeDetailResponse, WorkspaceVersionSummary } from "@/types/api";
import type { WorkspaceView } from "@/types/resume";

export const WORKSPACE_NAVIGATION_ERROR_TOAST_ID =
  "workspace-navigation-error";

interface RoutePreparationOptions {
  signal: AbortSignal;
}

export async function prepareWorkspaceEntry(
  view: "resume" | "settings",
  options: RoutePreparationOptions,
): Promise<PreparedWorkspaceRoute<"resume" | "settings">> {
  const [, source] = await Promise.all([
    preloadWorkspaceRoute(view),
    fetchWorkspaceRouteData(view === "resume" ? "resume-gallery" : "settings", {
      notifyOnError: false,
      signal: options.signal,
    }),
  ]);
  options.signal.throwIfAborted();
  return source.kind === "resume-gallery"
    ? { view: "resume", data: source.data }
    : { view: "settings", data: source.data };
}

export async function fetchWorkspacePageData<
  Kind extends LoadableWorkspaceRouteDataKind,
>(
  kind: Kind,
  persistence: WorkspacePreferencesPersistence,
  options: { signal: AbortSignal; notifyOnError?: boolean },
): Promise<WorkspaceRouteDataResult<Kind>> {
  const acceptPreferences = await persistence.prepareRead(options.signal);
  options.signal.throwIfAborted();
  const source = await fetchWorkspaceRouteData(kind, options);
  acceptPreferences(source.data);
  return source;
}

async function loadWorkspaceRouteData(
  view: WorkspaceView,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
): Promise<PreparedWorkspaceRoute> {
  await persistence.flush();

  switch (view) {
    case "resume": {
      const source = await fetchWorkspacePageData("resume-gallery", persistence, {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
    case "templates": {
      const source = await fetchWorkspacePageData("template-gallery", persistence, {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
    case "trash": {
      const source = await fetchWorkspacePageData("trash", persistence, {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
    case "models": {
      const source = await fetchWorkspacePageData("models", persistence, {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
    case "settings": {
      const source = await fetchWorkspacePageData("settings", persistence, {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
  }
}

export async function prepareWorkspaceRoute<View extends WorkspaceView>(
  view: View,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
): Promise<PreparedWorkspaceRoute<View>> {
  const [, prepared] = await Promise.all([
    preloadWorkspaceRoute(view),
    loadWorkspaceRouteData(view, persistence, options),
  ]);

  return prepared as PreparedWorkspaceRoute<View>;
}

export function preloadResumeDetailRoute() {
  return Promise.all([
    loadWorkspacePreferencesProvider(),
    loadResumeDetailWorkspacePage(),
    loadDocumentCanvas(),
  ]);
}

async function loadResumeEditorRouteData(
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
) {
  await persistence.flush();
  const source = await fetchWorkspacePageData("resume-detail", persistence, {
    notifyOnError: false,
    signal: options.signal,
  });
  return source.data;
}

export async function loadResumeDetailRouteData(
  resumeId: string,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
): Promise<PreparedResumeDetailRouteData> {
  await persistence.flush();

  const routeDataRequest = fetchWorkspacePageData("resume-detail", persistence, {
    notifyOnError: false,
    signal: options.signal,
  });
  const detailRequest = fetchResumeApi(resumeId, {
    notifyOnError: false,
    signal: options.signal,
  });
  const versionsRequest = fetchResumeVersionsApi(resumeId, {
    notifyOnError: false,
    signal: options.signal,
  }).catch((error) => {
    if (isAbortError(error)) {
      throw error;
    }
    return { versions: [] as WorkspaceVersionSummary[] };
  });
  const [routeSource, detail, versionsPayload] = await Promise.all([
    routeDataRequest,
    detailRequest,
    versionsRequest,
  ]);

  return {
    detail,
    routeData: routeSource.data,
    versions: versionsPayload.versions,
  };
}

export async function prepareResumeDetailRoute(
  resumeId: string,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
) {
  const [, prepared] = await Promise.all([
    preloadResumeDetailRoute(),
    loadResumeDetailRouteData(resumeId, persistence, options),
  ]);
  return prepared;
}

export async function prepareCreatedResumeDetailRoute(
  detail: ResumeDetailResponse,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
): Promise<PreparedResumeDetailRouteData> {
  const [, routeData] = await Promise.all([
    preloadResumeDetailRoute(),
    loadResumeEditorRouteData(persistence, options),
  ]);

  return {
    detail,
    routeData,
    versions: [
      { savedAt: detail.savedAt, versionId: detail.versionId },
    ],
  };
}

export function preloadTemplateDetailRoute() {
  return Promise.all([
    loadWorkspacePreferencesProvider(),
    loadTemplateDetailWorkspacePage(),
    loadDocumentCanvas(),
  ]);
}

export async function loadTemplateDetailRouteData(
  templateId: string,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
): Promise<WorkspaceTemplateRouteData> {
  await persistence.flush();
  const source = await fetchWorkspacePageData("template-detail", persistence, {
    notifyOnError: false,
    signal: options.signal,
  });
  const hasTarget =
    isBuiltinTemplateId(templateId) ||
    source.data.customTemplates.some((template) => template.id === templateId);
  if (!hasTarget) {
    throw new Error("Template target is unavailable.");
  }
  return source.data;
}

export async function prepareTemplateDetailRoute(
  templateId: string,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
) {
  const [, data] = await Promise.all([
    preloadTemplateDetailRoute(),
    loadTemplateDetailRouteData(templateId, persistence, options),
  ]);
  return data;
}
