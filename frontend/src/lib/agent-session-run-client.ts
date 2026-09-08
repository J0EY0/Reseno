import {
  apiRoutes,
  isApiErrorCode,
  requestApi,
} from "@/lib/api-client";
import { projectAgentDraftReview, type AgentDraftConflictResolution } from "@/lib/agent-draft-review";
import type {
  AgentChatMessage,
  AgentCommittedDraft,
  AgentDraftDecisionStatus,
  AgentDraftDecisionRequest,
  AgentDraftDecisionResponse,
  AgentRunResponse,
  AgentSessionRecoveryResponse,
  AgentSessionReplaceRequest,
  AgentSessionResponse,
  ResumeDetailResponse,
} from "@/types/api";
import type { ResumeData } from "@/types/resume";

type AgentDraftDecision =
  | {
      conflictResolution?: AgentDraftConflictResolution;
      currentResume: ResumeData;
      currentVersionId: string | null;
      rebaseOnLatest: boolean;
      reviewItemIds: string[];
      status: "applied";
    }
  | {
      reviewItemIds: string[];
      status: "discarded";
    };

export interface AgentDraftDecisionResolution {
  committed: boolean;
  draft: AgentCommittedDraft | null;
  resume: ResumeDetailResponse | null;
  resolvedAsRequested: boolean;
  session: AgentSessionResponse;
}

function agentDraftDecisionRoute(resumeId: string, messageId: string) {
  return `/api/agent/resumes/${encodeURIComponent(resumeId)}/session/messages/${encodeURIComponent(messageId)}/draft`;
}

function getAgentDraftResponse(
  session: AgentSessionResponse,
  messageId: string,
): AgentChatMessage | null {
  return session.messages.find((message) => message.id === messageId)?.response ?? null;
}

function getAgentCommittedDraft(
  session: AgentSessionResponse,
  messageId: string,
): AgentCommittedDraft | null {
  return getAgentDraftResponse(session, messageId)?.draft ?? null;
}

function getRequestedReviewItemState(
  draft: AgentCommittedDraft | null,
  reviewItemIds: string[],
  decisionStatus: AgentDraftDecisionStatus,
) {
  if (!draft) {
    return "unavailable" as const;
  }

  const requestedIds = new Set(reviewItemIds);
  const requestedItems = draft.reviewItems.filter((item) =>
    requestedIds.has(item.id),
  );
  if (
    requestedIds.size !== reviewItemIds.length ||
    requestedItems.length !== reviewItemIds.length
  ) {
    return "unavailable" as const;
  }
  if (requestedItems.every((item) => item.status === "pending")) {
    return "pending" as const;
  }
  if (requestedItems.every((item) => item.status === decisionStatus)) {
    return "resolved" as const;
  }
  return "changed" as const;
}

export function loadAgentSessionRecovery(
  resumeId: string,
  options: { notifyOnError?: boolean; signal?: AbortSignal } = {},
) {
  return requestApi<AgentSessionRecoveryResponse>(apiRoutes.agentResumeRecovery(resumeId), {
    cacheTtlMs: 0,
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
  formalResume: ResumeDetailResponse,
  candidateResume?: ResumeData,
): AgentDraftDecisionRequest {
  if (decision.status === "discarded") {
    return {
      revision,
      reviewItemIds: decision.reviewItemIds,
      status: "discarded",
    };
  }
  if (!candidateResume) {
    throw new Error("The Agent draft candidate is unavailable.");
  }
  return {
    expectedVersionId: formalResume.versionId,
    revision,
    reviewItemIds: decision.reviewItemIds,
    resume: candidateResume,
    status: "applied",
  };
}

export async function resolveAgentDraftDecision(
  resumeId: string,
  messageId: string,
  decision: AgentDraftDecision,
): Promise<AgentDraftDecisionResolution> {
  let [session, formalResume] = await Promise.all([
    loadAgentSession(resumeId),
    loadFormalResume(resumeId),
  ]);

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = getAgentDraftResponse(session, messageId);
    const currentDraft = response?.draft ?? null;
    const requestedState = getRequestedReviewItemState(
      currentDraft,
      decision.reviewItemIds,
      decision.status,
    );
    if (requestedState !== "pending") {
      return {
        committed: false,
        draft: currentDraft,
        resume: formalResume,
        resolvedAsRequested: requestedState === "resolved",
        session,
      };
    }

    try {
      let candidateResume: ResumeData | undefined;
      if (decision.status === "applied") {
        if (!response?.edits || !currentDraft) {
          throw new Error("The committed Agent draft is unavailable.");
        }
        const formalVersionChanged =
          decision.currentVersionId !== formalResume.versionId;
        if (
          formalVersionChanged &&
          (!decision.rebaseOnLatest || decision.conflictResolution)
        ) {
          throw new Error(
            "The formal resume changed before the draft decision completed.",
          );
        }
        const projection = projectAgentDraftReview({
          baseResume: currentDraft.baseResume,
          conflictResolution: decision.conflictResolution,
          currentResume: decision.rebaseOnLatest
            ? formalResume.resume.resume
            : decision.currentResume,
          edits: response.edits,
          reviewItemIds: decision.reviewItemIds,
          reviewItems: currentDraft.reviewItems,
        });
        if (projection.errors.length > 0) {
          throw new Error("The selected Agent draft no longer applies cleanly.");
        }
        candidateResume = projection.resume;
      }
      const request = createAgentDraftDecisionRequest(
        decision,
        session.revision,
        formalResume,
        candidateResume,
      );
      const updated = await updateAgentDraftDecision(
        resumeId,
        messageId,
        request,
      );
      return {
        committed: true,
        draft: getAgentCommittedDraft(updated.session, messageId),
        resume: updated.resume ?? formalResume,
        resolvedAsRequested: true,
        session: updated.session,
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
      const isResumeConflict = isApiErrorCode(
        error,
        "RESUME_VERSION_CONFLICT",
      );
      if (!isRevisionConflict && !isDecisionConflict && !isResumeConflict) {
        throw error;
      }

      [session, formalResume] = await Promise.all([
        loadAgentSession(resumeId),
        loadFormalResume(resumeId),
      ]);
      const authoritativeDraft = getAgentCommittedDraft(session, messageId);
      const authoritativeState = getRequestedReviewItemState(
        authoritativeDraft,
        decision.reviewItemIds,
        decision.status,
      );
      if (authoritativeState !== "pending") {
        return {
          committed: false,
          draft: authoritativeDraft,
          resume: formalResume,
          resolvedAsRequested: authoritativeState === "resolved",
          session,
        };
      }
      if (isDecisionConflict || attempt > 0) {
        throw error;
      }
    }
  }

  return {
    committed: false,
    draft: getAgentCommittedDraft(session, messageId),
    resume: formalResume,
    resolvedAsRequested: false,
    session,
  };
}
