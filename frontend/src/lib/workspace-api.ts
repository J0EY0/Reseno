import type { Locale } from "@/i18n";
import { apiRoutes, requestApi } from "@/lib/api-client";
import type {
  WorkspaceBootstrapResponse,
  WorkspaceBootstrapResult,
  WorkspaceResumeIdResponse,
  WorkspaceSaveRequest,
  WorkspaceSaveResponse,
  WorkspaceVersionResponse,
  WorkspaceVersionsResponse,
} from "@/types/api";
import type { AgentSettings, ThemeMode, WorkspaceSnapshot } from "@/types/resume";

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

export async function saveWorkspaceSnapshotApi(
  locale: Locale,
  snapshot: WorkspaceSnapshot,
) {
  const request: WorkspaceSaveRequest = {
    snapshot,
  };

  return requestApi<WorkspaceSaveResponse>(apiRoutes.workspaceSnapshot, {
    body: request,
    method: "PUT",
    searchParams: { locale },
  });
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

export function createWorkspaceResumeIdApi() {
  return requestApi<WorkspaceResumeIdResponse>(apiRoutes.workspaceResumeId, {
    method: "POST",
  });
}

export function fetchWorkspaceVersions(locale: Locale) {
  return requestApi<WorkspaceVersionsResponse>(apiRoutes.workspaceVersions, {
    cacheTtlMs: 3000,
    searchParams: { locale },
  });
}

export function fetchWorkspaceVersion(locale: Locale, versionId: string) {
  return requestApi<WorkspaceVersionResponse>(
    apiRoutes.workspaceVersion(versionId),
    {
      cacheTtlMs: 10000,
      searchParams: { locale },
    },
  );
}
