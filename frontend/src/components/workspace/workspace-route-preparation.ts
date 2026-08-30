import { isAbortError } from "@/lib/api-client";
import { isBuiltinTemplateId } from "@/lib/template-presets";
import {
  fetchResumeApi,
  fetchResumeVersionsApi,
  fetchWorkspaceRouteData,
} from "@/lib/workspace-api";
import type {
  PreparedResumeDetailRouteData,
  WorkspaceTemplateRouteData,
} from "@/lib/workspace-route-data";
import { loadDocumentPreviewCard } from "@/components/preview/document-preview-card-loader";
import {
  loadModelsWorkspacePage,
  loadResumeDetailWorkspacePage,
  loadResumeGalleryWorkspacePage,
  loadSettingsWorkspacePage,
  loadTemplateDetailWorkspacePage,
  loadTemplateGalleryWorkspacePage,
  loadTrashWorkspacePage,
  loadWorkspaceLateralLayout,
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

function loadWorkspaceRoute(view: WorkspaceView) {
  switch (view) {
    case "models":
      return loadModelsWorkspacePage();
    case "settings":
      return loadSettingsWorkspacePage();
    case "templates":
      return loadTemplateGalleryWorkspacePage();
    case "trash":
      return loadTrashWorkspacePage();
    case "resume":
      return loadResumeGalleryWorkspacePage();
  }
}

export function preloadWorkspaceRoute(view: WorkspaceView) {
  return Promise.all([
    loadWorkspaceLateralLayout(),
    loadWorkspaceRoute(view),
  ]);
}

async function loadWorkspaceRouteData(
  view: WorkspaceView,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
): Promise<PreparedWorkspaceRoute> {
  await persistence.flush();

  switch (view) {
    case "resume": {
      const source = await fetchWorkspaceRouteData("resume-gallery", {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
    case "templates": {
      const source = await fetchWorkspaceRouteData("template-gallery", {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
    case "trash": {
      const source = await fetchWorkspaceRouteData("trash", {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
    case "models": {
      const source = await fetchWorkspaceRouteData("models", {
        notifyOnError: false,
        signal: options.signal,
      });
      return { data: source.data, view };
    }
    case "settings": {
      const source = await fetchWorkspaceRouteData("settings", {
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
    loadResumeDetailWorkspacePage(),
    loadDocumentPreviewCard(),
  ]);
}

async function loadResumeEditorRouteData(
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
) {
  await persistence.flush();
  const source = await fetchWorkspaceRouteData("resume-detail", {
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

  const routeDataRequest = fetchWorkspaceRouteData("resume-detail", {
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
    loadTemplateDetailWorkspacePage(),
    loadDocumentPreviewCard(),
  ]);
}

export async function loadTemplateDetailRouteData(
  templateId: string,
  persistence: WorkspacePreferencesPersistence,
  options: RoutePreparationOptions,
): Promise<WorkspaceTemplateRouteData> {
  await persistence.flush();
  const source = await fetchWorkspaceRouteData("template-detail", {
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
