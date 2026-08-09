import { apiRoutes, requestApi } from "@/lib/api-client";
import type {
  AgentRunResponse,
  AgentSessionReplaceRequest,
  AgentSessionResponse,
} from "@/types/api";

export function loadActiveAgentRun(
  resumeId: string,
  options: { signal?: AbortSignal } = {},
) {
  return requestApi<AgentRunResponse | null>(apiRoutes.agentResumeRun(resumeId), {
    signal: options.signal,
  });
}

export function stopAgentRun(runId: string) {
  return requestApi<AgentRunResponse>(apiRoutes.agentRun(runId), {
    method: "DELETE",
  });
}

export async function loadAgentSession(
  resumeId: string,
  options: { signal?: AbortSignal } = {},
) {
  return requestApi<AgentSessionResponse>(apiRoutes.agentResumeSession(resumeId), {
    // Session revisions are optimistic-concurrency tokens. Reusing even a
    // short-lived GET cache can make an otherwise valid history edit stale.
    cacheTtlMs: 0,
    signal: options.signal,
  });
}

export async function replaceAgentSession(
  resumeId: string,
  request: AgentSessionReplaceRequest,
) {
  return requestApi<AgentSessionResponse>(apiRoutes.agentResumeSession(resumeId), {
    body: request,
    method: "PUT",
  });
}
