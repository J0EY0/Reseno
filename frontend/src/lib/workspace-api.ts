import type { Locale } from "@/i18n";
import { apiRoutes, requestApi } from "@/lib/api-client";
import {
  getWorkspaceRouteDataPath,
  type LoadableWorkspaceRouteDataKind,
  type WorkspaceRouteDataMap,
  type WorkspaceRouteDataResult,
} from "@/lib/workspace-route-data";
import type {
  ApiRequestOptions,
  DefaultTemplateSaveResponse,
  ResumeCreateRequest,
  ResumeDeleteResponse,
  ResumeDetailResponse,
  ResumeSaveMode,
  ResumeSaveRequest,
  ResumeTrashEmptyResponse,
  ResumeTrashResponse,
  TemplateDeleteResponse,
  TemplateDetailResponse,
  TemplateTrashEmptyResponse,
  TemplateTrashResponse,
  UserSettingsSaveResponse,
  WorkspaceVersionsResponse,
} from "@/types/api";
import type {
  AgentSettings,
  ResumeTemplateDefinition,
  ThemeMode,
} from "@/types/resume";

export async function fetchWorkspaceRouteData<
  Kind extends LoadableWorkspaceRouteDataKind,
>(
  routeKind: Kind,
  options: Pick<ApiRequestOptions, "notifyOnError" | "signal"> = {},
): Promise<WorkspaceRouteDataResult<Kind>> {
  const path = getWorkspaceRouteDataPath(routeKind);

  if (!path) {
    throw new Error("Unknown workspace route.");
  }

  const data = await requestApi<WorkspaceRouteDataMap[Kind]>(path, {
    cacheTtlMs: 3000,
    ...options,
  });

  return { kind: routeKind, data } as WorkspaceRouteDataResult<Kind>;
}

export function saveUserSettingsApi(
  locale: Locale,
  settings: {
    agentSettings?: AgentSettings;
    theme?: ThemeMode;
  },
) {
  return requestApi<UserSettingsSaveResponse>(apiRoutes.workspaceUserSettings, {
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

export function createResumeApi(request: ResumeCreateRequest = {}) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resumes, {
    body: request,
    method: "POST",
  });
}

export function duplicateResumeApi(resumeId: string, locale: Locale) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resumeDuplicate(resumeId), {
    method: "POST",
    searchParams: { locale },
  });
}

export function fetchResumeApi(
  resumeId: string,
  options: Pick<ApiRequestOptions, "notifyOnError" | "signal"> = {},
) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resume(resumeId), {
    cacheTtlMs: 3000,
    ...options,
  });
}

export function saveResumeApi(
  resumeId: string,
  request: ResumeSaveRequest,
  saveMode: ResumeSaveMode = "checkpoint",
  options: Pick<ApiRequestOptions, "notifyOnError"> = {},
) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resume(resumeId), {
    body: request,
    method: "PUT",
    searchParams: { saveMode },
    ...options,
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

export function fetchResumeVersionsApi(
  resumeId: string,
  options: Pick<ApiRequestOptions, "notifyOnError" | "signal"> = {},
) {
  return requestApi<WorkspaceVersionsResponse>(
    apiRoutes.resumeVersions(resumeId),
    {
      cacheTtlMs: 3000,
      ...options,
    },
  );
}

export function fetchResumeVersionApi(
  resumeId: string,
  versionId: string,
  options: Pick<ApiRequestOptions, "notifyOnError" | "signal"> = {},
) {
  return requestApi<ResumeDetailResponse>(
    apiRoutes.resumeVersion(resumeId, versionId),
    {
      cacheTtlMs: 10000,
      ...options,
    },
  );
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
