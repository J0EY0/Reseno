// @vitest-environment jsdom

import { act, cleanup, renderHook } from "@testing-library/react";
import type { FormEvent, PropsWithChildren } from "react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  PromptInputProvider,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input-context";
import { usePromptInputForm } from "@/components/ai-elements/use-prompt-input-form";
import { useAgentConversation } from "@/components/copilot/use-agent-conversation";
import { useAgentPromptActions } from "@/components/copilot/use-agent-prompt-actions";
import { prepareAgentAttachment } from "@/components/copilot/copilot-attachment-policy";
import { defaultMessages, loadMessages } from "@/i18n";
import {
  deletePendingAgentAttachment,
  uploadAgentAttachment,
} from "@/lib/agent-attachment-client";
import {
  loadAgentSession,
  loadAgentSessionRecovery,
  stopAgentRun,
} from "@/lib/agent-session-run-client";
import { fetchApiResource } from "@/lib/api-client";
import { createEmptyResume } from "@/lib/resume";
import type {
  AgentRunResponse,
  AgentSessionRecoveryResponse,
  AgentSessionResponse,
} from "@/types/api";
import type { ModelConfig } from "@/types/resume";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  fetchApiResource: vi.fn(),
  clearApiCache: vi.fn(),
}));
vi.mock("@/lib/agent-session-run-client", () => ({
  loadAgentSession: vi.fn(),
  loadAgentSessionRecovery: vi.fn(),
  replaceAgentSession: vi.fn(),
  stopAgentRun: vi.fn(),
}));
vi.mock("@/lib/agent-attachment-client", () => ({
  uploadAgentAttachment: vi.fn(),
  deletePendingAgentAttachment: vi.fn(),
}));
vi.mock(
  "@/components/copilot/copilot-attachment-policy",
  async (importOriginal) => ({
    ...(await importOriginal<
      typeof import("@/components/copilot/copilot-attachment-policy")
    >()),
    prepareAgentAttachment: vi.fn(),
  }),
);
vi.mock("@/lib/api-error-notifier", () => ({ notifyApiError: vi.fn() }));

const resume = createEmptyResume();
const model: ModelConfig = {
  id: "model-1",
  provider: "openai",
  providerLabel: "OpenAI",
  iconProvider: "openai",
  providerKind: "cloud",
  apiFamily: "openai_compatible_chat",
  nickname: "Test model",
  apiKeyPreview: "",
  model: "test-model",
  apiUrl: "https://model.test/v1",
  temperature: null,
  topP: null,
  maxTokens: null,
  contextWindowTokens: 100_000,
  supportsImage: true,
  supportsThinking: false,
  thinkingMode: "auto",
  availableThinkingModes: ["auto"],
  supportsTools: true,
  supportsStreaming: true,
};

function session(resumeId = "resume-1"): AgentSessionResponse {
  return { resumeId, revision: "revision-1", messages: [], executions: [] };
}

function draftSession(): AgentSessionResponse {
  return {
    ...session(),
    revision: "authoritative-revision",
    messages: [
      {
        id: "assistant-authoritative",
        role: "assistant",
        text: "Saved summary",
        createdAt: "2026-01-01T00:00:00Z",
        response: {
          id: "assistant-authoritative",
          role: "assistant",
          text: "Saved summary",
          transactionState: "committed",
          draft: {
            baseResume: resume,
            reviewItems: [
              {
                id: "review-authoritative",
                editIds: ["edit-authoritative"],
                status: "pending",
              },
            ],
          },
          edits: [
            {
              id: "edit-authoritative",
              target: "basic.summary",
              title: "Saved edit",
              reason: "Use the saved summary.",
              operation: {
                type: "replace_field",
                path: "basic.summary",
                value: "Saved summary",
              },
            },
          ],
        },
      },
    ],
  };
}

function activeRun(id = "run-1", resumeId = "resume-1"): AgentRunResponse {
  return {
    id,
    resumeId,
    baseResume: resume,
    status: "active",
    executionState: "running",
    errorCode: null,
    lastEventId: 0,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function eventResponse(text: string) {
  return new Response(text, {
    headers: { "Content-Type": "text/event-stream" },
  });
}

function openStream(runId = "run-1") {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(value) {
        controller = value;
      },
    }),
    {
      headers: {
        "Content-Type": "text/event-stream",
        "X-Agent-Run-Id": runId,
      },
    },
  );
  return {
    response,
    finish(text: string) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  };
}

const completedEvent =
  'id: 1\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}\n\n';
const cancelledEvent =
  'id: 1\nevent: run_done\ndata: {"status":"cancelled","executionState":"cancelled"}\n\n';

function composerProvider({ children }: PropsWithChildren) {
  return (
    <PromptInputProvider initialInput="Keep my original prompt">
      {children}
    </PromptInputProvider>
  );
}

function renderConversation({
  resumeId = "resume-1",
  onBeforeSend = vi.fn(async () => undefined),
} = {}) {
  const rollback = vi.fn();
  const reconcile = vi.fn();
  const preview = vi.fn();
  const decideDraft = vi.fn(async () => null);
  const hook = renderHook(
    ({ currentResumeId }) => {
      const conversation = useAgentConversation({
        agentDraftState: null,
        onApplyAgentDraft: decideDraft,
        onDiscardAgentDraft: decideDraft,
        documentLocale: "en",
        onBeforeSend,
        onPreviewAgentEdits: preview,
        onReconcileAgentDraft: reconcile,
        onRollbackAgentDraft: rollback,
        resume,
        resumeId: currentResumeId,
        selectedModelConfig: model,
        t: defaultMessages,
      });
      const prompt = useAgentPromptActions({
        hasConfiguredModel: true,
        isRequestBusy: conversation.requestPhase !== "idle",
        isSessionReady: conversation.isSessionReady,
        resumeId: currentResumeId,
        sessionResetVersion: conversation.sessionResetVersion,
        sendPrompt: conversation.sendPrompt,
        stopConversation: conversation.stopResponding,
        t: defaultMessages,
      });
      const composer = usePromptInputController();
      const form = usePromptInputForm({ onSubmit: prompt.submitPrompt });
      return { conversation, prompt, composer, form };
    },
    { wrapper: composerProvider, initialProps: { currentResumeId: resumeId } },
  );
  return { ...hook, rollback, reconcile };
}

function submitEvent() {
  return {
    preventDefault: vi.fn(),
    currentTarget: document.createElement("form"),
  } as unknown as FormEvent<HTMLFormElement>;
}

async function advance(milliseconds = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

beforeAll(async () => {
  await loadMessages("zh");
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = vi.fn(() => "data:application/pdf;base64,AA==");
      static revokeObjectURL = vi.fn();
    },
  );
  vi.mocked(loadAgentSession).mockImplementation(async (id) => session(id));
  vi.mocked(loadAgentSessionRecovery).mockImplementation(async (id) => ({
    session: session(id),
    run: null,
  }));
  vi.mocked(prepareAgentAttachment).mockResolvedValue({
    body: new FormData(),
    byteLength: 1,
  });
  vi.mocked(uploadAgentAttachment).mockResolvedValue({
    id: "uploaded-1",
    filename: "resume.pdf",
  });
  vi.mocked(deletePendingAgentAttachment).mockResolvedValue({
    id: "uploaded-1",
  });
});

afterEach(async () => {
  cleanup();
  await advance();
  const expectedFailures = new Set([
    "Failed to consume agent run.",
    "Failed to restore agent session.",
    "Failed to start or consume the Agent run.",
    "Failed to start the Agent request.",
  ]);
  const unexpectedErrors = vi
    .mocked(console.error)
    .mock.calls.filter(([message]) => !expectedFailures.has(String(message)));
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  expect(unexpectedErrors).toEqual([]);
});

describe("Agent submission and recovery", () => {
  it("waits for recovery before publishing history, a draft, or its revision to a send", async () => {
    const recovery = deferred<AgentSessionRecoveryResponse>();
    const authoritative = draftSession();
    const stream = openStream();
    vi.mocked(loadAgentSessionRecovery).mockReturnValue(recovery.promise);
    vi.mocked(fetchApiResource).mockResolvedValue(stream.response);
    const hook = renderConversation();
    await act(async () => {
      await expect(
        hook.result.current.prompt.submitPrompt({
          text: "Next prompt",
          files: [],
        }),
      ).rejects.toThrow("The Agent session is not ready for a new prompt.");
    });
    await advance(420);
    expect(hook.result.current.conversation.isSessionReady).toBe(false);
    expect(hook.result.current.conversation.messages).toEqual([]);
    expect(hook.reconcile).not.toHaveBeenCalled();
    expect(fetchApiResource).not.toHaveBeenCalled();
    expect(loadAgentSession).not.toHaveBeenCalled();

    await act(async () => {
      recovery.resolve({ session: authoritative, run: null });
    });
    expect(hook.result.current.conversation.isSessionReady).toBe(true);
    expect(hook.result.current.conversation.messages[0]).toMatchObject({
      id: "assistant-authoritative",
      text: "Saved summary",
    });
    expect(hook.reconcile).toHaveBeenCalledExactlyOnceWith({
      ...authoritative.messages[0].response!.draft,
      edits: authoritative.messages[0].response!.edits,
      sourceMessageId: "assistant-authoritative",
      transactionState: "committed",
    });
    let operation!: ReturnType<
      typeof hook.result.current.conversation.sendPrompt
    >;
    act(() => {
      operation = hook.result.current.conversation.sendPrompt("Next prompt");
    });
    await advance(420);
    expect(fetchApiResource).toHaveBeenCalledTimes(1);
    expect(
      JSON.parse(String(vi.mocked(fetchApiResource).mock.calls[0][1]?.body)),
    ).toMatchObject({ expectedRevision: "authoritative-revision" });
    await act(async () => stream.finish(completedEvent));
    expect(await operation.accepted).toBe(true);
    expect(await operation.completion).toBe("completed");
  });

  it("does not publish history, a draft, or a send after recovery fails", async () => {
    const recovery = deferred<AgentSessionRecoveryResponse>();
    vi.mocked(loadAgentSessionRecovery).mockReturnValue(recovery.promise);
    const hook = renderConversation();
    let operation!: ReturnType<
      typeof hook.result.current.conversation.sendPrompt
    >;
    act(() => {
      operation = hook.result.current.conversation.sendPrompt("Next prompt");
    });
    await advance(420);
    expect(hook.result.current.conversation.messages).toEqual([]);
    expect(hook.reconcile).not.toHaveBeenCalled();
    expect(fetchApiResource).not.toHaveBeenCalled();
    await act(async () => {
      recovery.reject(new Error("Session recovery failed"));
      expect(await operation.accepted).toBe(false);
      expect(await operation.completion).toBe("failed");
    });
    expect(hook.result.current.conversation.isSessionReady).toBe(false);
    expect(hook.result.current.conversation.sessionLoadError).toBe(true);
    expect(hook.result.current.conversation.messages).toEqual([]);
    expect(hook.reconcile).not.toHaveBeenCalled();
    expect(fetchApiResource).not.toHaveBeenCalled();
    expect(loadAgentSession).not.toHaveBeenCalled();
  });

  it("ignores cancelled recovery when a different resume is still loading", async () => {
    const previous = deferred<AgentSessionRecoveryResponse>();
    const current = deferred<AgentSessionRecoveryResponse>();
    vi.mocked(loadAgentSessionRecovery)
      .mockReturnValueOnce(previous.promise)
      .mockReturnValueOnce(current.promise);
    const hook = renderConversation();
    await advance();
    const signal = vi.mocked(loadAgentSessionRecovery).mock.calls[0][1]?.signal;
    hook.rerender({ currentResumeId: "resume-2" });
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      previous.resolve({ session: draftSession(), run: null });
    });
    expect(hook.result.current.conversation.messages).toEqual([]);
    expect(hook.result.current.conversation.isSessionReady).toBe(false);
    expect(hook.result.current.conversation.sessionLoadError).toBe(false);
    expect(hook.reconcile).not.toHaveBeenCalled();
    expect(fetchApiResource).not.toHaveBeenCalled();
    await act(async () => {
      current.resolve({
        session: { ...session("resume-2"), revision: "resume-2-revision" },
        run: null,
      });
    });
    expect(hook.result.current.conversation.isSessionReady).toBe(true);
    expect(hook.result.current.conversation.messages).toEqual([]);
    expect(hook.reconcile).toHaveBeenCalledExactlyOnceWith(null);
    const stream = openStream("resume-2-run");
    vi.mocked(fetchApiResource).mockResolvedValue(stream.response);
    let operation!: ReturnType<
      typeof hook.result.current.conversation.sendPrompt
    >;
    act(() => {
      operation = hook.result.current.conversation.sendPrompt("Current resume");
    });
    await advance(420);
    expect(fetchApiResource).toHaveBeenCalledTimes(1);
    expect(
      JSON.parse(String(vi.mocked(fetchApiResource).mock.calls[0][1]?.body)),
    ).toMatchObject({
      resumeId: "resume-2",
      expectedRevision: "resume-2-revision",
    });
    expect(await operation.accepted).toBe(true);
    await act(async () => stream.finish(completedEvent));
    expect(await operation.completion).toBe("completed");
  });

  it("does not reconcile a recovery snapshot that arrives after unmount", async () => {
    const recovery = deferred<AgentSessionRecoveryResponse>();
    vi.mocked(loadAgentSessionRecovery).mockReturnValue(recovery.promise);
    const hook = renderConversation();
    await advance();
    expect(hook.result.current.conversation.isSessionReady).toBe(false);
    expect(hook.reconcile).not.toHaveBeenCalled();
    const signal = vi.mocked(loadAgentSessionRecovery).mock.calls[0][1]?.signal;
    hook.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      recovery.resolve({ session: draftSession(), run: null });
    });
    expect(hook.reconcile).not.toHaveBeenCalled();
    expect(fetchApiResource).not.toHaveBeenCalled();
  });

  it("keeps rejected input and attachments for retry, then stops the accepted stream", async () => {
    let post = deferred<Response>();
    const stream = openStream();
    vi.mocked(fetchApiResource).mockImplementation(() => post.promise);
    vi.mocked(stopAgentRun).mockImplementation(async () => {
      stream.finish(
        'id: 1\nevent: message_done\ndata: {"message":{"id":"assistant-1","role":"assistant","text":"partial","transactionState":"rolled_back"}}\n\n' +
          'id: 2\nevent: run_done\ndata: {"status":"cancelled","executionState":"cancelled"}\n\n',
      );
      return activeRun();
    });
    const hook = renderConversation();
    await advance();
    expect(hook.result.current.conversation.status).toBe("ready");
    act(() => {
      hook.result.current.composer.attachments.add([
        new File(["resume"], "resume.pdf", { type: "application/pdf" }),
      ]);
      hook.result.current.prompt.referenceHistoryAttachment({
        id: "history-1",
        filename: "job.pdf",
      });
    });
    let submission: void;
    act(() => {
      submission = hook.result.current.form.handleSubmit(submitEvent());
    });
    await advance(420);
    expect(fetchApiResource).toHaveBeenCalledTimes(1);
    expect(hook.result.current.conversation.requestPhase).toBe("preparing");
    await act(async () => {
      post.reject(new TypeError("Failed to fetch"));
      await submission;
    });
    expect(hook.result.current.composer.textInput.value).toBe(
      "Keep my original prompt",
    );
    expect(hook.result.current.composer.attachments.files).toHaveLength(1);
    expect(hook.result.current.prompt.referencedAttachments).toHaveLength(1);
    expect(hook.result.current.conversation.messages).toHaveLength(0);
    expect(hook.result.current.conversation.requestPhase).toBe("idle");
    expect(deletePendingAgentAttachment).toHaveBeenCalledWith(
      "resume-1",
      "uploaded-1",
      { notifyOnError: false },
    );

    post = deferred<Response>();
    act(() => {
      submission = hook.result.current.form.handleSubmit(submitEvent());
    });
    await advance(420);
    expect(fetchApiResource).toHaveBeenCalledTimes(2);
    const request = vi.mocked(fetchApiResource).mock.calls[1][1];
    expect(
      JSON.parse(String(request?.body)).message.files.map(
        (file: { id: string }) => file.id,
      ),
    ).toEqual(["history-1", "uploaded-1"]);
    await act(async () => {
      post.resolve(stream.response);
      await submission;
    });
    expect(hook.result.current.composer.textInput.value).toBe("");
    expect(hook.result.current.composer.attachments.files).toHaveLength(0);
    expect(hook.result.current.prompt.referencedAttachments).toHaveLength(0);
    expect(hook.result.current.conversation.requestPhase).toBe("responding");
    await act(async () => {
      hook.result.current.conversation.stopResponding();
    });
    expect(stopAgentRun).toHaveBeenCalledExactlyOnceWith("run-1");
    expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(1);
    expect(fetchApiResource).toHaveBeenCalledTimes(2);
    expect(hook.result.current.conversation.requestPhase).toBe("idle");
    expect(hook.rollback).toHaveBeenCalledWith("assistant-1");
  });

  it("preserves partial text after bounded recovery is exhausted and reconnects when stopped", async () => {
    let stopped = false;
    let attempts = 0;
    const run = activeRun();
    vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
      session: session(),
      run,
    });
    vi.mocked(fetchApiResource).mockImplementation(async () => {
      attempts += 1;
      return eventResponse(
        stopped
          ? cancelledEvent
          : attempts === 1
            ? 'id: 41\nevent: text_delta\ndata: {"delta":"Partial response","timelinePartId":"text-1"}\n\n'
            : "",
      );
    });
    vi.mocked(stopAgentRun).mockImplementation(async () => {
      stopped = true;
      return run;
    });
    const hook = renderConversation();
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(fetchApiResource).toHaveBeenCalledTimes(6);
    expect(hook.result.current.conversation.sessionLoadError).toBe(true);
    expect(loadAgentSession).not.toHaveBeenCalled();
    expect(hook.result.current.conversation.requestPhase).toBe("responding");
    expect(hook.result.current.conversation.streamingMessage?.text).toBe(
      "Partial response",
    );
    expect(hook.result.current.conversation.visibleMessages).toEqual([
      expect.objectContaining({ text: "Partial response" }),
    ]);
    let rejected!: ReturnType<
      typeof hook.result.current.conversation.sendPrompt
    >;
    act(() => {
      rejected = hook.result.current.conversation.sendPrompt("Another prompt");
    });
    expect(await rejected.accepted).toBe(false);
    expect(await rejected.completion).toBe("cancelled");
    expect(fetchApiResource).toHaveBeenCalledTimes(6);
    await act(async () => {
      hook.result.current.conversation.stopResponding();
    });
    expect(stopAgentRun).toHaveBeenCalledExactlyOnceWith("run-1");
    expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(2);
    expect(fetchApiResource).toHaveBeenCalledTimes(7);
    expect(hook.result.current.conversation.requestPhase).toBe("idle");
    expect(hook.result.current.conversation.streamingMessage).toBeNull();
    expect(hook.result.current.conversation.sessionLoadError).toBe(false);
    await act(async () => {
      hook.result.current.conversation.stopResponding();
    });
    expect(stopAgentRun).toHaveBeenCalledTimes(1);
    expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(2);
    expect(fetchApiResource).toHaveBeenCalledTimes(7);

    const nextStream = openStream("next-run");
    vi.mocked(fetchApiResource).mockResolvedValueOnce(nextStream.response);
    let next!: ReturnType<typeof hook.result.current.conversation.sendPrompt>;
    act(() => {
      next = hook.result.current.conversation.sendPrompt("A fresh prompt");
    });
    await advance(420);
    expect(await next.accepted).toBe(true);
    expect(fetchApiResource).toHaveBeenCalledTimes(8);
    expect(hook.result.current.conversation.requestPhase).toBe("responding");
    await act(async () => nextStream.finish(completedEvent));
    expect(await next.completion).toBe("completed");
    expect(hook.result.current.conversation.requestPhase).toBe("idle");
  });

  it.each([false, true])(
    "retries a rejected subscription when the run has finished: %s",
    async (finished) => {
      const run = activeRun();
      vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
        session: session(),
        run,
      });
      vi.mocked(fetchApiResource).mockResolvedValue(
        new Response("Service unavailable", { status: 503 }),
      );
      const hook = renderConversation();
      await advance();
      expect(fetchApiResource).toHaveBeenCalledTimes(1);
      expect(hook.result.current.conversation.sessionLoadError).toBe(true);
      vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
        session: session(),
        run: finished ? null : run,
      });
      vi.mocked(fetchApiResource).mockImplementation(async () =>
        eventResponse(completedEvent),
      );
      await act(async () => {
        hook.result.current.conversation.retrySession();
      });
      expect(hook.result.current.conversation.sessionLoadError).toBe(false);
      expect(hook.result.current.conversation.requestPhase).toBe("idle");
      expect(hook.result.current.conversation.isSessionReady).toBe(true);
      expect(fetchApiResource).toHaveBeenCalledTimes(finished ? 1 : 2);
      await act(async () => {
        hook.result.current.conversation.stopResponding();
      });
      expect(stopAgentRun).not.toHaveBeenCalled();
      expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(2);
      expect(fetchApiResource).toHaveBeenCalledTimes(finished ? 1 : 2);
    },
  );

  it.each(["session retry", "resume change"])(
    "ignores an older stop response after %s loads another active run",
    async (transition) => {
      const stop = deferred<AgentRunResponse>();
      const newStream = openStream("new-run");
      vi.mocked(stopAgentRun).mockReturnValue(stop.promise);
      vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
        session: session(),
        run: activeRun("old-run"),
      });
      vi.mocked(fetchApiResource).mockResolvedValue(
        new Response("Service unavailable", { status: 503 }),
      );
      const hook = renderConversation();
      await advance();
      act(() => hook.result.current.conversation.stopResponding());
      expect(stopAgentRun).toHaveBeenCalledExactlyOnceWith("old-run");
      vi.mocked(fetchApiResource).mockResolvedValue(newStream.response);
      vi.mocked(loadAgentSessionRecovery).mockImplementation(async (id) => ({
        session: session(id),
        run: activeRun("new-run", id),
      }));
      if (transition === "resume change") {
        hook.rerender({ currentResumeId: "resume-2" });
      } else {
        act(() => hook.result.current.conversation.retrySession());
      }
      await advance();
      expect(hook.result.current.conversation.requestPhase).toBe("responding");
      expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(2);
      const signal = vi.mocked(fetchApiResource).mock.calls[1][1]?.signal;
      await act(async () => {
        stop.resolve({ ...activeRun("old-run"), status: "cancelled" });
      });
      expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(2);
      expect(hook.result.current.conversation.requestPhase).toBe("responding");
      expect(signal?.aborted).toBe(false);
      await act(async () => newStream.finish(completedEvent));
    },
  );

  it("preserves a newer prompt and added attachment across acceptance rerenders", async () => {
    const post = deferred<Response>();
    const stream = openStream();
    vi.mocked(fetchApiResource).mockReturnValue(post.promise);
    const hook = renderConversation();
    await advance();
    let submission: void;
    act(() => {
      submission = hook.result.current.form.handleSubmit(submitEvent());
    });
    await advance(420);
    act(() => {
      hook.result.current.composer.textInput.setInput("The next prompt");
      hook.result.current.composer.attachments.add([
        new File(["next"], "next.txt"),
      ]);
    });
    await act(async () => {
      post.resolve(stream.response);
      await submission;
    });
    expect(hook.result.current.composer.textInput.value).toBe(
      "The next prompt",
    );
    expect(
      hook.result.current.composer.attachments.files.map(
        (file) => file.filename,
      ),
    ).toEqual(["next.txt"]);
    expect(hook.result.current.conversation.requestPhase).toBe("responding");
    await act(async () => stream.finish(completedEvent));
  });

  it("cancels a queued send on unmount without posting it", async () => {
    const hook = renderConversation();
    await advance();
    let operation!: ReturnType<
      typeof hook.result.current.conversation.sendPrompt
    >;
    act(() => {
      operation = hook.result.current.conversation.sendPrompt("queued prompt");
    });
    await advance();
    expect(operation.submitted).toBe(true);
    expect(hook.result.current.conversation.requestPhase).toBe("preparing");
    hook.unmount();
    await act(async () => {
      await vi.runAllTimersAsync();
      expect(await operation.accepted).toBe(false);
      expect(await operation.completion).toBe("cancelled");
    });
    expect(fetchApiResource).not.toHaveBeenCalled();
  });

  it("aborts an attachment upload on unmount without submitting a late response", async () => {
    const upload =
      deferred<Awaited<ReturnType<typeof uploadAgentAttachment>>>();
    vi.mocked(uploadAgentAttachment).mockReturnValue(upload.promise);
    const hook = renderConversation();
    await advance();
    act(() =>
      hook.result.current.composer.attachments.add([
        new File(["resume"], "resume.pdf"),
      ]),
    );
    let submission: void;
    act(() => {
      submission = hook.result.current.form.handleSubmit(submitEvent());
    });
    await advance();
    expect(hook.result.current.prompt.isSubmittingPrompt).toBe(true);
    const signal = vi.mocked(uploadAgentAttachment).mock.calls[0][2]?.signal;
    hook.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      upload.reject(new DOMException("Upload aborted", "AbortError"));
      await submission;
      await vi.runAllTimersAsync();
    });
    expect(fetchApiResource).not.toHaveBeenCalled();
  });

  it("aborts a disconnected subscription on unmount and cancels its scheduled reconnect", async () => {
    vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
      session: session(),
      run: activeRun(),
    });
    vi.mocked(fetchApiResource).mockImplementation(async () =>
      eventResponse(""),
    );
    const hook = renderConversation();
    await advance();
    expect(fetchApiResource).toHaveBeenCalledTimes(1);
    const signal = vi.mocked(fetchApiResource).mock.calls[0][1]?.signal;
    hook.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(fetchApiResource).toHaveBeenCalledTimes(1);
  });
});
