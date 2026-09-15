import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import { useAgentConversation } from "@/components/copilot/use-agent-conversation";
import { getMessagesSync, loadMessages } from "@/i18n";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";
import {
  loadAgentSession,
  loadAgentSessionRecovery,
} from "@/lib/agent-session-run-client";
import { connectAgentRun } from "@/lib/agent-stream-client";
import type { AgentDraftSnapshot, AgentSessionResponse } from "@/types/api";
import { createResume } from "./helpers/agent-edit-fixtures";

vi.mock("@/lib/agent-session-run-client", async (original) => ({
  ...(await original<typeof import("@/lib/agent-session-run-client")>()),
  loadAgentSessionRecovery: vi.fn(),
  loadAgentSession: vi.fn(),
}));
vi.mock("@/lib/agent-stream-client", async (original) => ({
  ...(await original<typeof import("@/lib/agent-stream-client")>()),
  connectAgentRun: vi.fn(),
}));

function history(revision: string) {
  const baseResume = createResume();
  const snapshot: AgentDraftSnapshot = {
    baseResume,
    sourceMessageId: `draft-${revision}`,
    transactionState: "committed",
    edits: [
      {
        id: "edit-summary",
        title: "Summary",
        target: "basic.summary",
        reason: "Requested summary",
        operation: {
          type: "replace_field",
          path: "basic.summary",
          value: `Summary ${revision}`,
        },
      },
    ],
    reviewItems: [
      { id: "review-summary", editIds: ["edit-summary"], status: "pending" },
    ],
  };
  const texts = [
    ...en.agentTransientModelStatusTexts,
    ...zh.agentTransientModelStatusTexts,
  ];
  const session: AgentSessionResponse = {
    resumeId: "resume-a",
    revision,
    executions: [],
    messages: [
      ...texts.map((text, index) => ({
        id: `${revision}-${index}`,
        role: "assistant" as const,
        text: ` ${text} `,
        createdAt: "2026-01-01",
        response: {
          id: `${revision}-${index}`,
          role: "assistant" as const,
          text: ` ${text} `,
        },
      })),
      {
        id: snapshot.sourceMessageId,
        role: "assistant",
        createdAt: "2026-01-01",
        text: `Actual answer / 实际回答 ${revision}`,
        response: {
          id: snapshot.sourceMessageId,
          role: "assistant",
          text: `Actual answer / 实际回答 ${revision}`,
          transactionState: "committed",
          edits: snapshot.edits,
          draft: { baseResume, reviewItems: snapshot.reviewItems },
        },
      },
    ],
  };
  return {
    session,
    snapshot,
    expected: [...texts.map(() => ""), `Actual answer / 实际回答 ${revision}`],
  };
}

beforeAll(() => loadMessages("zh"));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

it.each(["en", "zh"] as const)(
  "hydrates both languages on initial recovery and terminal refresh while the document locale is %s",
  async (documentLocale) => {
    const initial = history("initial"),
      refreshed = history("refreshed");
    const completed =
      Promise.withResolvers<Awaited<ReturnType<typeof connectAgentRun>>>();
    const refreshedSession = Promise.withResolvers<AgentSessionResponse>();
    const run = {
      id: "run-a",
      resumeId: "resume-a",
      baseResume: initial.snapshot.baseResume,
      status: "active" as const,
      executionState: "running" as const,
      errorCode: null,
      lastEventId: 1,
    };
    vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
      session: initial.session,
      run,
    });
    vi.mocked(connectAgentRun).mockReturnValue(completed.promise);
    vi.mocked(loadAgentSession).mockReturnValue(refreshedSession.promise);
    const reconcile = vi.fn();
    const { result } = renderHook(() =>
      useAgentConversation({
        agentDraftState: null,
        documentLocale,
        onApplyAgentDraft: vi.fn(),
        onDiscardAgentDraft: vi.fn(),
        onPreviewAgentEdits: vi.fn(),
        onReconcileAgentDraft: reconcile,
        onRollbackAgentDraft: vi.fn(),
        resume: initial.snapshot.baseResume,
        resumeId: "resume-a",
        selectedModelConfig: null,
        t: getMessagesSync(documentLocale),
      }),
    );
    await act(async () => undefined);
    expect(loadAgentSessionRecovery).toHaveBeenCalledExactlyOnceWith(
      "resume-a",
      { notifyOnError: false, signal: expect.any(AbortSignal) },
    );
    expect(result.current.messages.map((message) => message.text)).toEqual(
      initial.expected,
    );
    expect(
      result.current.messages.map((message) => message.response?.text),
    ).toEqual(initial.expected);
    expect(reconcile).toHaveBeenCalledExactlyOnceWith(initial.snapshot);
    expect(connectAgentRun).toHaveBeenCalledWith(
      run,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(loadAgentSession).not.toHaveBeenCalled();
    await act(async () => {
      completed.resolve({
        runId: run.id,
        message: { id: "terminal", role: "assistant", text: "Finished" },
        status: "completed",
        executionState: "succeeded",
        errorCode: null,
        lastEventId: 2,
        messageDone: true,
      });
    });
    expect(loadAgentSession).toHaveBeenCalledExactlyOnceWith("resume-a");
    expect(reconcile).toHaveBeenCalledTimes(1);
    await act(async () => {
      refreshedSession.resolve(refreshed.session);
    });
    expect(result.current.messages.map((message) => message.text)).toEqual(
      refreshed.expected,
    );
    expect(
      result.current.messages.map((message) => message.response?.text),
    ).toEqual(refreshed.expected);
    expect(reconcile).toHaveBeenLastCalledWith(refreshed.snapshot);
    expect(reconcile).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("ready");
  },
);
