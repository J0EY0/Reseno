import type {
  AgentSettings,
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ModelConfig,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeWorkspaceItem,
  ThemeMode,
} from "@/types/resume";

export type WorkspaceRouteDataKind =
  | "resume-gallery"
  | "resume-detail"
  | "template-gallery"
  | "template-detail"
  | "trash"
  | "models"
  | "settings"
  | "pdf-export"
  | "unknown";

export type LoadableWorkspaceRouteDataKind = Exclude<
  WorkspaceRouteDataKind,
  "unknown"
>;

interface WorkspaceRoutePreferences {
  theme?: ThemeMode;
}

export interface WorkspaceTemplateRouteData
  extends WorkspaceRoutePreferences {
  defaultTemplateId: ResumeTemplateId;
  customTemplates: ResumeTemplateDefinition[];
}

export interface ResumeGalleryRouteData
  extends WorkspaceTemplateRouteData {
  resumes: ResumeWorkspaceItem[];
}

export interface ResumeEditorRouteData
  extends WorkspaceTemplateRouteData {
  modelConfigs: ModelConfig[];
  agentSettings: AgentSettings;
}

export type TemplateRouteData = WorkspaceTemplateRouteData;

export interface TrashRouteData extends WorkspaceTemplateRouteData {
  deletedResumes: DeletedResumeWorkspaceItem[];
  deletedTemplates: DeletedResumeTemplateDefinition[];
}

export interface ModelSettingsRouteData
  extends WorkspaceRoutePreferences {
  modelConfigs: ModelConfig[];
  agentSettings: AgentSettings;
}

export interface WorkspaceRouteDataMap {
  "resume-gallery": ResumeGalleryRouteData;
  "resume-detail": ResumeEditorRouteData;
  "template-gallery": TemplateRouteData;
  "template-detail": TemplateRouteData;
  trash: TrashRouteData;
  models: ModelSettingsRouteData;
  settings: ModelSettingsRouteData;
  "pdf-export": TemplateRouteData;
}

export type WorkspaceRouteDataResult<
  Kind extends LoadableWorkspaceRouteDataKind =
    LoadableWorkspaceRouteDataKind,
> = Kind extends LoadableWorkspaceRouteDataKind
  ? { kind: Kind; data: WorkspaceRouteDataMap[Kind] }
  : never;

const workspaceRouteDataPathByKind = {
  "resume-gallery": "/api/workspace/pages/resumes",
  "resume-detail": "/api/workspace/pages/resume-editor",
  "template-gallery": "/api/workspace/pages/templates",
  "template-detail": "/api/workspace/pages/templates",
  trash: "/api/workspace/pages/trash",
  models: "/api/workspace/pages/models",
  settings: "/api/workspace/pages/settings",
  "pdf-export": "/api/workspace/pages/templates",
} as const satisfies Record<LoadableWorkspaceRouteDataKind, string>;

export function getWorkspaceRouteDataPath(
  routeKind: WorkspaceRouteDataKind,
): string | null {
  if (routeKind === "unknown") {
    return null;
  }

  return workspaceRouteDataPathByKind[routeKind];
}
