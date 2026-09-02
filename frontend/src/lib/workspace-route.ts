import { matchPath } from "react-router-dom";

import type { DocumentLocale, WorkspaceView } from "@/types/resume";
import type {
  PreparedResumeDetailRouteData,
  WorkspaceTemplateRouteData,
} from "@/lib/workspace-route-data";

export type WorkspaceRoute =
  | { kind: "resume-gallery" }
  | { kind: "resume-detail"; id: string }
  | { kind: "template-gallery" }
  | { kind: "template-detail"; id: string }
  | { kind: "trash" }
  | { kind: "models" }
  | { kind: "settings" }
  | { kind: "unknown" };

function hasDefaultTemplateIds(value: unknown) {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return typeof candidate.zh === "string" && typeof candidate.en === "string";
}

export interface TemplateDetailRouteHandoff {
  data: WorkspaceTemplateRouteData;
  kind: "template-detail-handoff";
  templateLocale: DocumentLocale;
  templateId: string;
}

export interface ResumeDetailRouteHandoff {
  kind: "resume-detail-handoff";
  payload: PreparedResumeDetailRouteData;
  resumeCount: number;
  resumeId: string;
  resumeOrdinal: number;
}

export function createResumeDetailRouteHandoff(
  payload: PreparedResumeDetailRouteData,
  resumeOrdinal: number,
  resumeCount: number,
): ResumeDetailRouteHandoff {
  return {
    kind: "resume-detail-handoff",
    payload,
    resumeCount,
    resumeId: payload.detail.resume.id,
    resumeOrdinal,
  };
}

export function getResumeDetailRouteHandoff(
  state: unknown,
  resumeId: string,
): ResumeDetailRouteHandoff | null {
  if (!state || typeof state !== "object") {
    return null;
  }

  const candidate = state as Partial<ResumeDetailRouteHandoff>;
  const payload = candidate.payload;
  if (
    candidate.kind !== "resume-detail-handoff" ||
    candidate.resumeId !== resumeId ||
    payload?.detail?.resume?.id !== resumeId ||
    !payload.routeData ||
    !hasDefaultTemplateIds(payload.routeData.defaultTemplateIds) ||
    !Array.isArray(payload.routeData.customTemplates) ||
    !Array.isArray(payload.routeData.modelConfigs) ||
    !payload.routeData.agentSettings ||
    !Array.isArray(payload.versions) ||
    !Number.isInteger(candidate.resumeCount) ||
    !Number.isInteger(candidate.resumeOrdinal) ||
    Number(candidate.resumeOrdinal) < 1 ||
    Number(candidate.resumeCount) < Number(candidate.resumeOrdinal)
  ) {
    return null;
  }

  return candidate as ResumeDetailRouteHandoff;
}

export function createTemplateDetailRouteHandoff(
  templateId: string,
  data: WorkspaceTemplateRouteData,
  templateLocale: DocumentLocale,
): TemplateDetailRouteHandoff {
  return {
    data,
    kind: "template-detail-handoff",
    templateId,
    templateLocale,
  };
}

export function getTemplateDetailRouteHandoff(
  state: unknown,
  templateId: string,
): TemplateDetailRouteHandoff | null {
  if (!state || typeof state !== "object") {
    return null;
  }

  const candidate = state as Partial<TemplateDetailRouteHandoff>;
  if (
    candidate.kind !== "template-detail-handoff" ||
    candidate.templateId !== templateId ||
    (candidate.templateLocale !== "zh" && candidate.templateLocale !== "en") ||
    !candidate.data ||
    !hasDefaultTemplateIds(candidate.data.defaultTemplateIds) ||
    !Array.isArray(candidate.data.customTemplates)
  ) {
    return null;
  }

  return candidate as TemplateDetailRouteHandoff;
}

export const workspaceRoutePaths = {
  resumeGallery: "/resume",
  resumeDetail: "/resume/:id",
  templateGallery: "/templates",
  templateDetail: "/template/:id",
  trash: "/trash",
  models: "/models",
  settings: "/settings",
} as const;

export const workspaceAppRoutePaths = Object.values(workspaceRoutePaths);

const workspacePathByView: Record<WorkspaceView, string> = {
  resume: workspaceRoutePaths.resumeGallery,
  templates: workspaceRoutePaths.templateGallery,
  trash: workspaceRoutePaths.trash,
  models: workspaceRoutePaths.models,
  settings: workspaceRoutePaths.settings,
};

export function getWorkspacePath(view: WorkspaceView) {
  return workspacePathByView[view];
}

export function getWorkspaceRoute(pathname: string): WorkspaceRoute {
  const resumeDetailMatch = matchPath(workspaceRoutePaths.resumeDetail, pathname);

  if (resumeDetailMatch?.params.id) {
    return { kind: "resume-detail", id: resumeDetailMatch.params.id };
  }

  const templateDetailMatch = matchPath(
    workspaceRoutePaths.templateDetail,
    pathname,
  );

  if (templateDetailMatch?.params.id) {
    return { kind: "template-detail", id: templateDetailMatch.params.id };
  }

  if (
    matchPath(
      { path: workspaceRoutePaths.resumeGallery, end: true },
      pathname,
    )
  ) {
    return { kind: "resume-gallery" };
  }

  if (matchPath(workspaceRoutePaths.templateGallery, pathname)) {
    return { kind: "template-gallery" };
  }

  if (matchPath(workspaceRoutePaths.trash, pathname)) {
    return { kind: "trash" };
  }

  if (matchPath(workspaceRoutePaths.models, pathname)) {
    return { kind: "models" };
  }

  if (matchPath(workspaceRoutePaths.settings, pathname)) {
    return { kind: "settings" };
  }

  return { kind: "unknown" };
}

export function getWorkspaceViewFromRoute(route: WorkspaceRoute): WorkspaceView {
  switch (route.kind) {
    case "template-gallery":
    case "template-detail":
      return "templates";
    case "trash":
      return "trash";
    case "models":
      return "models";
    case "settings":
      return "settings";
    case "resume-gallery":
    case "resume-detail":
    case "unknown":
    default:
      return "resume";
  }
}

export function getResumePath(resumeId: string) {
  return `/resume/${resumeId}`;
}

export function getTemplatePath(templateId: string) {
  return `/template/${templateId}`;
}
