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
  ResumeTrashResponse,
  TemplateDeleteResponse,
  TemplateDetailResponse,
  TemplateEditingResponse,
  TemplateSaveMode,
  TemplateArtifactItem,
  TemplateTrashResponse,
  UserSettingsSaveResponse,
  WorkspaceVersionsResponse,
} from "@/types/api";
import type {
  AgentSettings,
  DocumentLocale,
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

export function saveDefaultTemplateApi(
  documentLocale: DocumentLocale,
  templateId: string,
) {
  return requestApi<DefaultTemplateSaveResponse>(
    apiRoutes.workspaceDefaultTemplate,
    {
      body: { documentLocale, templateId },
      method: "PUT",
    },
  );
}

export function createResumeApi(
  request: ResumeCreateRequest,
  options: Pick<ApiRequestOptions, "notifyOnError"> = {},
) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resumes, {
    body: request,
    method: "POST",
    ...options,
  });
}

export function duplicateResumeApi(resumeId: string) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resumeDuplicate(resumeId), {
    method: "POST",
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

export function createTemplateApi(
  template: ResumeTemplateDefinition | TemplateArtifactItem,
  options: Pick<ApiRequestOptions, "notifyOnError"> = {},
) {
  return requestApi<TemplateDetailResponse>(apiRoutes.templates, {
    body: { template: createTemplateSavePayload(template) },
    method: "POST",
    ...options,
  });
}

export function fetchTemplateApi(
  templateId: string,
  options: Pick<ApiRequestOptions, "notifyOnError" | "signal"> = {},
) {
  return requestApi<TemplateEditingResponse>(apiRoutes.template(templateId), {
    cacheTtlMs: 3000,
    ...options,
  });
}

export function saveTemplateApi(
  templateId: string,
  template: ResumeTemplateDefinition,
  options: Pick<ApiRequestOptions, "notifyOnError"> & {
    saveMode?: TemplateSaveMode;
  } = {},
) {
  const { saveMode = "checkpoint", ...requestOptions } = options;
  return requestApi<TemplateEditingResponse>(apiRoutes.template(templateId), {
    body: { template: createTemplateSavePayload(template), saveMode },
    method: "PUT",
    ...requestOptions,
  });
}

export function discardTemplateChangesApi(templateId: string) {
  return requestApi<TemplateEditingResponse>(
    `${apiRoutes.template(templateId)}/discard`,
    { method: "POST" },
  );
}

function createTemplateSavePayload(
  template: ResumeTemplateDefinition | TemplateArtifactItem,
): TemplateArtifactItem {
  return {
    preset: template.preset,
    name: template.name,
    description: template.description,
    layout: template.layout,
    typography: template.typography,
    settings: template.settings,
  };
}

export function moveTemplateToTrashApi(
  templateId: string,
  options: Pick<ApiRequestOptions, "notifyOnError"> = {},
) {
  return requestApi<TemplateTrashResponse>(
    apiRoutes.templateTrash(templateId),
    {
      method: "POST",
      ...options,
    },
  );
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
