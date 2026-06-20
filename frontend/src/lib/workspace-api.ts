import type { Locale } from "@/i18n";
import { apiRoutes, requestApi } from "@/lib/api-client";
import type {
  DefaultTemplateSaveResponse,
  DeletedResumeListResponse,
  DeletedTemplateListResponse,
  ResumeCreateRequest,
  ResumeDeleteResponse,
  ResumeDetailResponse,
  ResumeListResponse,
  ResumeSaveRequest,
  ResumeTrashEmptyResponse,
  ResumeTrashResponse,
  TemplateDeleteResponse,
  TemplateDetailResponse,
  TemplateListResponse,
  TemplateTrashEmptyResponse,
  TemplateTrashResponse,
  WorkspaceBootstrapResponse,
  WorkspaceBootstrapResult,
  WorkspaceVersionsResponse,
} from "@/types/api";
import type {
  AgentSettings,
  ResumeTemplateDefinition,
  ThemeMode,
} from "@/types/resume";

export async function fetchWorkspaceBootstrap(
  locale: Locale,
): Promise<WorkspaceBootstrapResult> {
  const workspace = await requestApi<WorkspaceBootstrapResponse>(
    apiRoutes.workspaceBootstrap,
    {
      cacheTtlMs: 3000,
      searchParams: { locale },
    },
  );

  return {
    workspace,
    savedAt:
      "savedAt" in workspace && typeof workspace.savedAt === "string"
        ? workspace.savedAt
        : null,
    source: "backend",
  };
}

export function saveUserSettingsApi(
  locale: Locale,
  settings: {
    agentSettings?: AgentSettings;
    theme?: ThemeMode;
  },
) {
  return requestApi<Record<string, unknown>>(apiRoutes.workspaceUserSettings, {
    body: { settings },
    method: "PUT",
    searchParams: { locale },
  });
}

export function saveDefaultTemplateApi(templateId: string) {
  return requestApi<DefaultTemplateSaveResponse>(
    apiRoutes.workspaceDefaultTemplate,
    {
      body: { templateId },
      method: "PUT",
    },
  );
}

export function fetchResumesApi(status: "active" = "active") {
  return requestApi<ResumeListResponse>(apiRoutes.resumes, {
    cacheTtlMs: 3000,
    searchParams: { status },
  });
}

export function fetchDeletedResumesApi() {
  return requestApi<DeletedResumeListResponse>(apiRoutes.resumes, {
    cacheTtlMs: 3000,
    searchParams: { status: "deleted" },
  });
}

export function createResumeApi(request: ResumeCreateRequest = {}) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resumes, {
    body: request,
    method: "POST",
  });
}

export function fetchResumeApi(resumeId: string) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resume(resumeId), {
    cacheTtlMs: 3000,
  });
}

export function saveResumeApi(resumeId: string, request: ResumeSaveRequest) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resume(resumeId), {
    body: request,
    method: "PUT",
  });
}

export function moveResumeToTrashApi(resumeId: string) {
  return requestApi<ResumeTrashResponse>(apiRoutes.resumeTrash(resumeId), {
    method: "POST",
  });
}

export function restoreResumeApi(resumeId: string) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resumeRestore(resumeId), {
    method: "POST",
  });
}

export function deleteResumeForeverApi(resumeId: string) {
  return requestApi<ResumeDeleteResponse>(apiRoutes.resume(resumeId), {
    method: "DELETE",
  });
}

export function emptyResumeTrashApi() {
  return requestApi<ResumeTrashEmptyResponse>(apiRoutes.resumeTrashEmpty, {
    method: "DELETE",
  });
}

export function fetchResumeVersionsApi(resumeId: string) {
  return requestApi<WorkspaceVersionsResponse>(
    apiRoutes.resumeVersions(resumeId),
    {
      cacheTtlMs: 3000,
    },
  );
}

export function fetchResumeVersionApi(resumeId: string, versionId: string) {
  return requestApi<ResumeDetailResponse>(
    apiRoutes.resumeVersion(resumeId, versionId),
    {
      cacheTtlMs: 10000,
    },
  );
}

export function fetchTemplatesApi(status: "active" = "active") {
  return requestApi<TemplateListResponse>(apiRoutes.templates, {
    cacheTtlMs: 3000,
    searchParams: { status },
  });
}

export function fetchDeletedTemplatesApi() {
  return requestApi<DeletedTemplateListResponse>(apiRoutes.templates, {
    cacheTtlMs: 3000,
    searchParams: { status: "deleted" },
  });
}

export function createTemplateApi(template: ResumeTemplateDefinition) {
  return requestApi<TemplateDetailResponse>(apiRoutes.templates, {
    body: { template },
    method: "POST",
  });
}

export function saveTemplateApi(
  templateId: string,
  template: ResumeTemplateDefinition,
) {
  return requestApi<TemplateDetailResponse>(apiRoutes.template(templateId), {
    body: { template },
    method: "PUT",
  });
}

export function moveTemplateToTrashApi(templateId: string) {
  return requestApi<TemplateTrashResponse>(apiRoutes.templateTrash(templateId), {
    method: "POST",
  });
}

export function restoreTemplateApi(templateId: string) {
  return requestApi<TemplateDetailResponse>(
    apiRoutes.templateRestore(templateId),
    {
      method: "POST",
    },
  );
}

export function deleteTemplateForeverApi(templateId: string) {
  return requestApi<TemplateDeleteResponse>(apiRoutes.template(templateId), {
    method: "DELETE",
  });
}

export function emptyTemplateTrashApi() {
  return requestApi<TemplateTrashEmptyResponse>(apiRoutes.templateTrashEmpty, {
    method: "DELETE",
  });
}
