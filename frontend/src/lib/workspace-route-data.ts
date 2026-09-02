import type {
  AgentSettings,
  DefaultTemplateIds,
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ModelConfig,
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
  ThemeMode,
} from "@/types/resume";
import type {
  ResumeDetailResponse,
  WorkspaceVersionSummary,
} from "@/types/api";

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
  defaultTemplateIds: DefaultTemplateIds;
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

export interface PreparedResumeDetailRouteData {
  detail: ResumeDetailResponse;
  routeData: ResumeEditorRouteData;
  versions: WorkspaceVersionSummary[];
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
  routeKind: LoadableWorkspaceRouteDataKind,
): string {
  return workspaceRouteDataPathByKind[routeKind];
}
