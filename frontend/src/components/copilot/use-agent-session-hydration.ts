import { useEffect } from "react";

import { loadAgentSessionRecovery } from "@/lib/agent-session-run-client";
import { connectAgentRun } from "@/lib/agent-stream-client";
import { isAbortError } from "@/lib/api-client";

import {
  setAgentRequestPhase,
  type AgentConversationRuntimeRef,
  type AgentConversationUpdates,
} from "./agent-conversation-runtime";
import { hydrateAgentSession } from "./copilot-message-model";
import type { ConsumeAgentRunStream } from "./use-agent-run-stream";

export function useAgentSessionHydration({
  cancelScheduledSend,
  consumeRunStream,
  resumeId,
  retryAttempt,
  runtimeRef,
  updates,
}: {
  cancelScheduledSend: (rollback: boolean) => boolean;
  consumeRunStream: ConsumeAgentRunStream;
  resumeId?: string;
  retryAttempt: number;
  runtimeRef: AgentConversationRuntimeRef;
  updates: AgentConversationUpdates;
}) {
  useEffect(() => {
    const runtime = runtimeRef.current;
    let cancelled = false;
    const abortController = new AbortController();
    let resolveSessionReady: () => void = () => undefined;
    let sessionReadyResolved = false;
    const sessionReadyPromise = new Promise<void>((resolve) => {
      resolveSessionReady = resolve;
    });
    const releaseSessionWaiters = () => {
      if (sessionReadyResolved) {
        return;
      }
      sessionReadyResolved = true;
      resolveSessionReady();
    };

    runtime.activeRequestAbort?.abort();
    runtime.activeRequestAbort = abortController;
    runtime.sessionReady = false;
    runtime.sessionReadyPromise = sessionReadyPromise;
    runtime.activeRun = null;
    runtime.stopRequested = false;
    runtime.previewedEditsKey = null;

    cancelScheduledSend(false);

    updates.setMessages([]);
    updates.setStreamingMessage(null);
    setAgentRequestPhase(runtime, updates, "idle");
    updates.setSessionLoadError(false);
    updates.setSessionReady(false);
    runtime.sessionRevision = null;
    runtime.optimisticMessageOwner = null;

    if (!resumeId) {
      runtime.sessionReady = true;
      updates.setSessionReady(true);
      releaseSessionWaiters();
      runtime.sessionReadyPromise = null;
      runtime.activeRequestAbort = null;
      return () => {
        cancelled = true;
        abortController.abort();
      };
    }

    void (async () => {
      try {
        const recovery = await loadAgentSessionRecovery(resumeId, {
          notifyOnError: false,
          signal: abortController.signal,
        });
        const { draftSnapshot, panelMessages, session } =
          await hydrateAgentSession(Promise.resolve(recovery.session));
        if (cancelled || runtime.activeRequestAbort !== abortController) {
          return;
        }
        const { run } = recovery;

        updates.setMessages(panelMessages);
        runtime.sessionRevision = session.revision;
        runtime.onReconcileAgentDraft(draftSnapshot);
        runtime.sessionReady = true;
        updates.setSessionReady(true);
        releaseSessionWaiters();
        if (!run || run.status !== "active") {
          if (runtime.activeRequestAbort === abortController) {
            runtime.activeRequestAbort = null;
          }
          return;
        }

        runtime.requestResume = run.baseResume;
        runtime.activeRun = run;
        setAgentRequestPhase(runtime, updates, "responding");
        await consumeRunStream(
          (options) => connectAgentRun(run, options),
          abortController,
        );
      } catch (error) {
        releaseSessionWaiters();
        if (
          !cancelled &&
          runtime.activeRequestAbort === abortController &&
          !isAbortError(error)
        ) {
          console.error("Failed to restore agent session.", error);
          updates.setSessionLoadError(true);
        }
        if (runtime.activeRequestAbort === abortController) {
          runtime.activeRequestAbort = null;
        }
      } finally {
        releaseSessionWaiters();
        if (runtime.sessionReadyPromise === sessionReadyPromise) {
          runtime.sessionReadyPromise = null;
        }
      }
    })();

    return () => {
      cancelled = true;
      releaseSessionWaiters();
      abortController.abort();
      if (runtime.sessionReadyPromise === sessionReadyPromise) {
        runtime.sessionReadyPromise = null;
      }
      if (runtime.activeRequestAbort === abortController) {
        runtime.activeRequestAbort = null;
      }
    };
  }, [
    cancelScheduledSend,
    consumeRunStream,
    resumeId,
    retryAttempt,
    runtimeRef,
    updates,
  ]);
}
