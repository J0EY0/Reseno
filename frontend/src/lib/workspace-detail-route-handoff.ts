import {
  createWorkspaceHandoffToken,
  readWorkspaceHandoffToken,
} from "@/lib/workspace-route-handoff";
import type { DocumentLocale } from "@/types/resume";
import type {
  PreparedResumeDetailRouteData,
  PreparedTemplateDetailRouteData,
} from "@/lib/workspace-route-data";

function hasDefaultTemplateIds(value: unknown) {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return typeof candidate.zh === "string" && typeof candidate.en === "string";
}

interface TemplateDetailRouteHandoff {
  data: PreparedTemplateDetailRouteData;
  kind: "template-detail-handoff";
  templateLocale: DocumentLocale;
  templateId: string;
}

interface ResumeDetailRouteHandoff {
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
): { kind: "resume-detail-handoff"; token: string } {
  const detail: ResumeDetailRouteHandoff = {
    kind: "resume-detail-handoff",
    payload,
    resumeCount,
    resumeId: payload.detail.resume.id,
    resumeOrdinal,
  };
  return { kind: detail.kind, token: createWorkspaceHandoffToken(detail) };
}

export function getResumeDetailRouteHandoff(
  state: unknown,
  resumeId: string,
): ResumeDetailRouteHandoff | null {
  if (!state || typeof state !== "object") {
    return null;
  }

  if (
    !("kind" in state) ||
    state.kind !== "resume-detail-handoff" ||
    !("token" in state)
  ) {
    return null;
  }
  const candidate = readWorkspaceHandoffToken(state.token) as
    Partial<ResumeDetailRouteHandoff> | undefined;
  if (!candidate) {
    return null;
  }
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
  data: PreparedTemplateDetailRouteData,
  templateLocale: DocumentLocale,
): { kind: "template-detail-handoff"; token: string } {
  const detail: TemplateDetailRouteHandoff = {
    data,
    kind: "template-detail-handoff",
    templateId,
    templateLocale,
  };
  return { kind: detail.kind, token: createWorkspaceHandoffToken(detail) };
}

export function getTemplateDetailRouteHandoff(
  state: unknown,
  templateId: string,
): TemplateDetailRouteHandoff | null {
  if (!state || typeof state !== "object") {
    return null;
  }

  if (
    !("kind" in state) ||
    state.kind !== "template-detail-handoff" ||
    !("token" in state)
  ) {
    return null;
  }
  const candidate = readWorkspaceHandoffToken(state.token) as
    Partial<TemplateDetailRouteHandoff> | undefined;
  if (!candidate) {
    return null;
  }
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
