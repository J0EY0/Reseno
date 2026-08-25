import {
  apiRoutes,
  isApiErrorCode,
  requestApi,
} from "@/lib/api-client";
import type {
  AgentDraftDecisionRequest,
  AgentDraftDecisionResponse,
  AgentDraftStatus,
  AgentRunResponse,
  AgentSessionReplaceRequest,
  AgentSessionResponse,
  ResumeDetailResponse,
} from "@/types/api";

type AgentDraftDecision =
  | Omit<
      Extract<AgentDraftDecisionRequest, { status: "applied" }>,
      "expectedVersionId" | "revision"
    >
  | Omit<
      Extract<AgentDraftDecisionRequest, { status: "discarded" }>,
      "revision"
    >;

export interface AgentDraftDecisionResolution {
  committed: boolean;
  resume: ResumeDetailResponse | null;
  session: AgentSessionResponse;
  status: AgentDraftStatus | null;
}

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
  options: { notifyOnError?: boolean; signal?: AbortSignal } = {},
) {
  return requestApi<AgentRunResponse | null>(apiRoutes.agentResumeRun(resumeId), {
    notifyOnError: options.notifyOnError,
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
  options: { notifyOnError?: boolean; signal?: AbortSignal } = {},
) {
  return requestApi<AgentSessionResponse>(apiRoutes.agentResumeSession(resumeId), {
    // Session revisions are optimistic-concurrency tokens. Reusing even a
    // short-lived GET cache can make an otherwise valid history edit stale.
    cacheTtlMs: 0,
    notifyOnError: options.notifyOnError,
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
  return requestApi<AgentDraftDecisionResponse>(
    agentDraftDecisionRoute(resumeId, messageId),
    {
      body: request,
      method: "PATCH",
      notifyOnError: false,
    },
  );
}

function loadFormalResume(resumeId: string) {
  return requestApi<ResumeDetailResponse>(apiRoutes.resume(resumeId), {
    cacheTtlMs: 0,
    notifyOnError: false,
  });
}

function createAgentDraftDecisionRequest(
  decision: AgentDraftDecision,
  revision: string,
  formalResume: ResumeDetailResponse | null,
): AgentDraftDecisionRequest {
  if (decision.status === "discarded") {
    return { ...decision, revision };
  }
  if (!formalResume) {
    throw new Error("The formal resume version is unavailable.");
  }
  return {
    ...decision,
    expectedVersionId: formalResume.versionId,
    revision,
  };
}

export async function resolveAgentDraftDecision(
  resumeId: string,
  messageId: string,
  decision: AgentDraftDecision,
): Promise<AgentDraftDecisionResolution> {
  const [initialSession, formalResume] = await Promise.all([
    loadAgentSession(resumeId),
    decision.status === "applied"
      ? loadFormalResume(resumeId)
      : Promise.resolve(null),
  ]);
  let session = initialSession;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const currentStatus = getAgentDraftStatus(session, messageId);
    if (currentStatus !== "pending") {
      return {
        committed: false,
        resume:
          currentStatus === "applied"
            ? await loadFormalResume(resumeId)
            : null,
        session,
        status: currentStatus,
      };
    }

    try {
      const request = createAgentDraftDecisionRequest(
        decision,
        session.revision,
        formalResume,
      );
      const updated = await updateAgentDraftDecision(
        resumeId,
        messageId,
        request,
      );
      return {
        committed: decision.status === "applied",
        resume: updated.resume,
        session: updated.session,
        status: getAgentDraftStatus(updated.session, messageId),
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
        return {
          committed: false,
          resume:
            authoritativeStatus === "applied"
              ? await loadFormalResume(resumeId)
              : null,
          session,
          status: authoritativeStatus,
        };
      }
      if (!isRevisionConflict || attempt > 0) {
        throw error;
      }
    }
  }

  return {
    committed: false,
    resume: null,
    session,
    status: getAgentDraftStatus(session, messageId),
  };
}
