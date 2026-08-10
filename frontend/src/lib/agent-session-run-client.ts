import {
  apiRoutes,
  isApiErrorCode,
  requestApi,
} from "@/lib/api-client";
import type {
  AgentDraftDecisionRequest,
  AgentDraftDecisionStatus,
  AgentDraftStatus,
  AgentRunResponse,
  AgentSessionReplaceRequest,
  AgentSessionResponse,
} from "@/types/api";

function agentDraftDecisionRoute(resumeId: string, messageId: string) {
  return `/api/agent/resumes/${encodeURIComponent(resumeId)}/session/messages/${encodeURIComponent(messageId)}/draft`;
}

function getAgentDraftStatus(
  session: AgentSessionResponse,
  messageId: string,
): AgentDraftStatus | null {
  return (
    session.messages.find((message) => message.id === messageId)?.response
      ?.draft?.status ?? null
  );
}

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

async function updateAgentDraftDecision(
  resumeId: string,
  messageId: string,
  request: AgentDraftDecisionRequest,
) {
  return requestApi<AgentSessionResponse>(
    agentDraftDecisionRoute(resumeId, messageId),
    {
      body: request,
      method: "PATCH",
      notifyOnError: false,
    },
  );
}

export async function resolveAgentDraftDecision(
  resumeId: string,
  messageId: string,
  status: AgentDraftDecisionStatus,
) {
  let session = await loadAgentSession(resumeId);

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const currentStatus = getAgentDraftStatus(session, messageId);
    if (currentStatus !== "pending") {
      return { session, status: currentStatus };
    }

    try {
      const updated = await updateAgentDraftDecision(resumeId, messageId, {
        revision: session.revision,
        status,
      });
      return {
        session: updated,
        status: getAgentDraftStatus(updated, messageId),
      };
    } catch (error) {
      const isRevisionConflict = isApiErrorCode(
        error,
        "AGENT_SESSION_REVISION_CONFLICT",
      );
      const isDecisionConflict = isApiErrorCode(
        error,
        "AGENT_DRAFT_DECISION_CONFLICT",
      );
      if (!isRevisionConflict && !isDecisionConflict) {
        throw error;
      }

      session = await loadAgentSession(resumeId);
      const authoritativeStatus = getAgentDraftStatus(session, messageId);
      if (authoritativeStatus !== "pending") {
        return { session, status: authoritativeStatus };
      }
      if (!isRevisionConflict || attempt > 0) {
        throw error;
      }
    }
  }

  return { session, status: getAgentDraftStatus(session, messageId) };
}
