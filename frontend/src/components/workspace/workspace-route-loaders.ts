import { createRouteLoader } from "@/lib/route-loader";

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
