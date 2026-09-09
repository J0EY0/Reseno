import {
  getWorkspacePath,
  getWorkspaceRoute,
  type WorkspaceRouteKind,
} from "@/lib/workspace-route";
import { createRouteLoader } from "@/lib/route-loader";
import type { WorkspaceView } from "@/types/resume";

export const loadWorkspacePreferencesProvider = createRouteLoader(
  () => import("@/components/workspace/workspace-preferences"),
  "WorkspacePreferencesProvider",
);

export const loadWorkspaceLateralLayout = createRouteLoader(
  () => import("@/components/workspace/workspace-lateral-layout"),
  "WorkspaceLateralLayout",
);

export const loadResumeGalleryWorkspacePage = createRouteLoader(
  () => import("@/components/workspace/resume-gallery-workspace-page"),
  "ResumeGalleryWorkspacePage",
);

export const loadModelsWorkspacePage = createRouteLoader(
  () => import("@/components/workspace/models-workspace-page"),
  "ModelsWorkspacePage",
);

export const loadSettingsWorkspacePage = createRouteLoader(
  () => import("@/components/workspace/settings-workspace-page"),
  "SettingsWorkspacePage",
);

export const loadTemplateGalleryWorkspacePage = createRouteLoader(
  () => import("@/components/workspace/template-gallery-workspace-page"),
  "TemplateGalleryWorkspacePage",
);

export const loadTrashWorkspacePage = createRouteLoader(
  () => import("@/components/workspace/trash-workspace-page"),
  "TrashWorkspacePage",
);

export const loadResumeDetailWorkspacePage = createRouteLoader(
  () => import("@/components/workspace/resume-detail-workspace-page"),
  "ResumeDetailWorkspacePage",
);

export const loadTemplateDetailWorkspacePage = createRouteLoader(
  () => import("@/components/workspace/template-detail-workspace-page"),
  "TemplateDetailWorkspacePage",
);

const workspaceRouteLoaders = {
  "resume-gallery": loadResumeGalleryWorkspacePage,
  "resume-detail": loadResumeDetailWorkspacePage,
  "template-gallery": loadTemplateGalleryWorkspacePage,
  "template-detail": loadTemplateDetailWorkspacePage,
  models: loadModelsWorkspacePage,
  settings: loadSettingsWorkspacePage,
  trash: loadTrashWorkspacePage,
  unknown: loadResumeGalleryWorkspacePage,
} satisfies Record<WorkspaceRouteKind, () => Promise<unknown>>;

export function getWorkspaceRouteLoader(pathname: string) {
  return workspaceRouteLoaders[getWorkspaceRoute(pathname).kind];
}

export function preloadWorkspaceRoute(view: WorkspaceView) {
  return Promise.all([
    loadWorkspacePreferencesProvider(),
    loadWorkspaceLateralLayout(),
    getWorkspaceRouteLoader(getWorkspacePath(view))(),
  ]);
}
