import {
  apiRoutes,
  fetchApiResource,
  requestApi,
  uploadApi,
} from "@/lib/api-client";
import type { AgentChatAttachment, ApiRequestOptions } from "@/types/api";

export function uploadAgentAttachment(
  file: FormData,
  resumeId: string,
  options: {
    onProgress?: (progress: { loaded: number; total?: number }) => void;
    signal?: AbortSignal;
  } = {},
) {
  file.set("resumeId", resumeId);
  return uploadApi<AgentChatAttachment>(apiRoutes.agentAttachments, file, {
    onProgress: options.onProgress,
    signal: options.signal,
  });
}

export function downloadAgentAttachment(
  resumeId: string,
  attachmentId: string,
) {
  return fetchApiResource(apiRoutes.agentAttachment(resumeId, attachmentId), {
    cache: "no-store",
  });
}

export function deletePendingAgentAttachment(
  resumeId: string,
  attachmentId: string,
  options: Pick<ApiRequestOptions, "notifyOnError"> = {},
) {
  return requestApi<{ id: string }>(
    apiRoutes.agentAttachment(resumeId, attachmentId),
    {
      method: "DELETE",
      ...options,
    },
  );
}
