import type { ApiRequestOptions } from "@/types/api";
import { AUTH_REFRESH_ROUTE } from "@/lib/api-auth";
import { notifyApiError } from "@/lib/api-error-notifier";
import {
  clearApiCache,
  fetchApiResponse,
  getApiPathname,
  requestApiEnvelope,
  uploadApiEnvelope,
  type ApiResourceOptions,
  type ApiUploadOptions,
} from "@/lib/api-request-core";

export { clearApiCache, resolveApiUrl } from "@/lib/api-request-core";
export {
  getApiErrorStatus,
  isAbortError,
  isApiErrorCode,
} from "@/lib/api-errors";

export const apiRoutes = {
  authSetup: "/api/auth/setup",
  authLogin: "/api/auth/login",
  authRefresh: AUTH_REFRESH_ROUTE,
  authPassword: "/api/auth/password",
  workspaceDefaultTemplate: "/api/workspace/default-template",
  workspaceUserSettings: "/api/workspace/user-settings",
  resumes: "/api/resumes",
  resume: (resumeId: string) => `/api/resumes/${resumeId}`,
  resumeDuplicate: (resumeId: string) => `/api/resumes/${resumeId}/duplicate`,
  resumeTrash: (resumeId: string) => `/api/resumes/${resumeId}/trash`,
  resumeRestore: (resumeId: string) => `/api/resumes/${resumeId}/restore`,
  resumeVersions: (resumeId: string) => `/api/resumes/${resumeId}/versions`,
  resumeVersion: (resumeId: string, versionId: string) =>
    `/api/resumes/${resumeId}/versions/${versionId}`,
  templates: "/api/templates",
  template: (templateId: string) => `/api/templates/${templateId}`,
  templateTrash: (templateId: string) => `/api/templates/${templateId}/trash`,
  templateRestore: (templateId: string) =>
    `/api/templates/${templateId}/restore`,
  modelConfigs: "/api/model-configs",
  modelProviders: "/api/model-providers",
  modelProviderDiscovery: "/api/model-providers/discover-models",
  modelContextWindow: "/api/model-providers/context-window",
  agentResumeSession: (resumeId: string) =>
    `/api/agent/resumes/${encodeURIComponent(resumeId)}/session`,
  agentResumeRecovery: (resumeId: string) =>
    `/api/agent/resumes/${encodeURIComponent(resumeId)}/recovery`,
  agentRun: (runId: string) => `/api/agent/runs/${encodeURIComponent(runId)}`,
  agentRunEvents: (runId: string) =>
    `/api/agent/runs/${encodeURIComponent(runId)}/events`,
  agentAttachments: "/api/agent/attachments",
  agentAttachment: (resumeId: string, attachmentId: string) =>
    `/api/agent/resumes/${encodeURIComponent(resumeId)}/attachments/${encodeURIComponent(attachmentId)}`,
  agentChat: "/api/agent/chat",
  resumePdfExport: "/api/exports/resume-pdf",
  resumeImagesExport: "/api/exports/resume-images",
  resumeImport: "/api/import/resume",
  templateImport: "/api/import/templates",
  sectionRegistry: "/api/section-registry",
  resumeImportLexicon: "/api/resume-import-lexicon",
} as const;

function invalidateMutationCache(route: string) {
  const pathname = getApiPathname(route);
  const resource = pathname.split("/").slice(0, 3).join("/");
  if (resource !== "/api/workspace") clearApiCache(resource);

  let pages: string[];
  if (
    resource === "/api/templates" ||
    pathname === apiRoutes.workspaceDefaultTemplate
  ) {
    clearApiCache("/api/resumes");
    pages = ["resumes", "templates", "resume-editor", "trash"];
  } else if (resource === "/api/resumes" || resource === "/api/agent") {
    if (resource === "/api/agent") clearApiCache("/api/resumes");
    pages = ["resumes", "trash"];
  } else if (resource === "/api/model-configs") {
    pages = ["models", "settings", "resume-editor"];
  } else {
    if (resource === "/api/workspace") clearApiCache("/api/workspace/pages");
    return;
  }
  for (const page of pages) clearApiCache(`/api/workspace/pages/${page}`);
}

async function withApiPolicy<T>(
  request: Promise<T>,
  route: string,
  method: string,
  options: Pick<ApiRequestOptions, "notifyOnError">,
) {
  try {
    const result = await request;
    if (method !== "GET" && method !== "HEAD") invalidateMutationCache(route);
    return result;
  } catch (error) {
    if (options.notifyOnError !== false) {
      notifyApiError(error);
    }
    throw error;
  }
}

export function requestApi<T>(route: string, options: ApiRequestOptions = {}) {
  return withApiPolicy(
    requestApiEnvelope<T>(route, options),
    route,
    options.method ?? "GET",
    options,
  );
}

export function uploadApi<T>(
  route: string,
  body: FormData,
  options: ApiUploadOptions = {},
) {
  return withApiPolicy(
    uploadApiEnvelope<T>(route, body, options),
    route,
    "POST",
    options,
  );
}

export function fetchApiResource(
  url: string,
  { notifyOnError, ...init }: ApiResourceOptions = {},
) {
  return withApiPolicy(
    fetchApiResponse(url, init),
    url,
    (init.method ?? "GET").toUpperCase(),
    { notifyOnError },
  );
}
