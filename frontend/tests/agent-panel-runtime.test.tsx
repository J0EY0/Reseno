import { act, cleanup, renderHook } from "@testing-library/react";
import {
  useState,
  useLayoutEffect,
  type FormEvent,
  type PropsWithChildren,
} from "react";
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
import {
  selectActivePromptSubmissionFiles,
  shouldClearPromptSubmissionText,
  usePromptInputForm,
} from "@/components/ai-elements/use-prompt-input-form";
import {
  isPendingSendOwner,
  setAgentRequestPhase,
  useAgentConversationRuntime,
  type AgentConversationUpdates,
  type AgentRequestPhase,
} from "@/components/copilot/agent-conversation-runtime";
import { useAgentConversation } from "@/components/copilot/use-agent-conversation";
import { useAgentPromptActions } from "@/components/copilot/use-agent-prompt-actions";
import { defaultMessages as t, loadMessages } from "@/i18n";
import {
  deletePendingAgentAttachment,
  uploadAgentAttachment,
} from "@/lib/agent-attachment-client";
import {
  loadAgentSession,
  loadAgentSessionRecovery,
  replaceAgentSession,
} from "@/lib/agent-session-run-client";
import { fetchApiResource } from "@/lib/api-client";
import { createEmptyResume } from "@/lib/resume";
import type { AgentSessionResponse } from "@/types/api";
import type { ModelConfig } from "@/types/resume";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
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
vi.mock("@/lib/api-error-notifier", () => ({ notifyApiError: vi.fn() }));

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
function session(id = "resume-1", text = "persisted"): AgentSessionResponse {
  return {
    resumeId: id,
    revision: `${id}-revision`,
    executions: [],
    messages: [
      {
        id: `history-${id}`,
        role: "user",
        text,
        createdAt: "2026-01-01T00:00:00Z",
      },
    ],
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function advance(ms = 0) {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}
function mountConversation(
  options: Partial<Parameters<typeof useAgentConversation>[0]> = {},
) {
  const props = {
    agentDraftState: null,
    documentLocale: "en" as const,
    onApplyAgentDraft: vi.fn(async () => null),
    onDiscardAgentDraft: vi.fn(async () => null),
    onPreviewAgentEdits: vi.fn(),
    onReconcileAgentDraft: vi.fn(),
    onRollbackAgentDraft: vi.fn(),
    resume: createEmptyResume(),
    resumeId: "resume-1",
    selectedModelConfig: model,
    t,
    ...options,
  };
  return {
    ...renderHook((input) => useAgentConversation(input), {
      initialProps: props,
    }),
    props,
  };
}
function completedResponse(status = "completed") {
  return new Response(
    `id: 1\nevent: message_done\ndata: {"message":{"id":"assistant-final","text":"kept partial","transactionState":"${status === "cancelled" ? "rolled_back" : "committed"}"}}\n\nid: 2\nevent: run_done\ndata: {"status":"${status}","executionState":"${status === "completed" ? "succeeded" : status}"}\n\n`,
    {
      headers: {
        "Content-Type": "text/event-stream",
        "X-Agent-Run-Id": "run-1",
      },
    },
  );
}

beforeAll(() => loadMessages("zh"));
beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.mocked(loadAgentSessionRecovery).mockImplementation(async (id) => ({
    session: session(id),
    run: null,
  }));
  vi.mocked(loadAgentSession).mockImplementation(async (id) => session(id));
  vi.mocked(fetchApiResource).mockImplementation(async () =>
    completedResponse(),
  );
});
afterEach(() => {
  cleanup();
  expect(
    vi
      .mocked(console.error)
      .mock.calls.filter(
        ([message]) =>
          ![
            "Failed to consume agent run.",
            "Failed to refresh the Agent session revision.",
            "Failed to start or consume the Agent run.",
            "Failed to start the Agent request.",
          ].includes(String(message)),
      ),
  ).toEqual([]);
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Agent request ownership", () => {
  it.each(["idle", "preparing", "responding"] as const)(
    "publishes %s only after the synchronous request gate changes",
    (phase) => {
      const hook = renderHook(() =>
        useAgentConversationRuntime({
          requestPhase: "idle",
          onPreviewAgentEdits: vi.fn(),
          onReconcileAgentDraft: vi.fn(),
          onRollbackAgentDraft: vi.fn(),
          resume: createEmptyResume(),
          resumeId: "resume-1",
          t,
        }),
      );
      const published: AgentRequestPhase[][] = [];
      const updates: AgentConversationUpdates = {
        setMessages: vi.fn(),
        setRequestPhase: (value) =>
          published.push([hook.result.current.current.requestPhase, value]),
        setSessionLoadError: vi.fn(),
        setSessionReady: vi.fn(),
        setStreamingMessage: vi.fn(),
      };
      setAgentRequestPhase(hook.result.current.current, updates, phase);
      expect(published).toEqual([[phase, phase]]);
    },
  );
  it.each([
    ["user-1", "user-1", "resume-1", "resume-1", true],
    [null, "user-1", "resume-1", "resume-1", false],
    ["user-2", "user-1", "resume-1", "resume-1", false],
    ["user-1", "user-1", "resume-1", "resume-2", false],
  ] as const)(
    "allows rollback only for owner %s / send %s / resume %s→%s",
    (current, pending, pendingResume, currentResume, expected) => {
      expect(
        isPendingSendOwner(current, pending, pendingResume, currentResume),
      ).toBe(expected);
    },
  );
  it.each(["stop", "unmount", "resume change"])(
    "cancels suspended preference preflight on %s without a late POST",
    async (action) => {
      const flush = deferred<void>();
      const hook = mountConversation({ onBeforeSend: () => flush.promise });
      await advance();
      let operation!: ReturnType<typeof hook.result.current.sendPrompt>;
      act(() => {
        operation = hook.result.current.sendPrompt("queued");
      });
      await advance();
      expect(hook.result.current.requestPhase).toBe("preparing");
      expect(hook.result.current.status).toBe("responding");
      expect(fetchApiResource).not.toHaveBeenCalled();
      if (action === "stop") act(() => hook.result.current.stopResponding());
      else if (action === "unmount") hook.unmount();
      else hook.rerender({ ...hook.props, resumeId: "resume-2" });
      await advance();
      if (action === "resume change")
        await act(async () => {
          flush.resolve();
        });
      expect(await operation.accepted).toBe(false);
      expect(await operation.completion).toBe("cancelled");
      await act(async () => {
        flush.resolve();
      });
      await advance(1000);
      expect(fetchApiResource).not.toHaveBeenCalled();
      if (action !== "unmount") {
        expect(hook.result.current.requestPhase).toBe("idle");
        expect(hook.result.current.status).toBe("ready");
      }
    },
  );
  it.each(["bootstrap", "missing revision"])(
    "checks Stop ownership after awaiting %s",
    async (boundary) => {
      const pending = deferred<AgentSessionResponse>();
      if (boundary === "bootstrap")
        vi.mocked(loadAgentSessionRecovery).mockImplementation(async () => ({
          session: await pending.promise,
          run: null,
        }));
      else {
        vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
          session: { ...session(), revision: "" },
          run: null,
        });
        vi.mocked(loadAgentSession).mockReturnValue(pending.promise);
      }
      const hook = mountConversation();
      await advance();
      let operation!: ReturnType<typeof hook.result.current.sendPrompt>;
      act(() => {
        operation = hook.result.current.sendPrompt("waiting for session");
      });
      await advance();
      if (boundary === "missing revision")
        expect(loadAgentSession).toHaveBeenCalledTimes(1);
      act(() => hook.result.current.stopResponding());
      await act(async () => pending.resolve(session()));
      await advance(1000);
      expect(await operation.accepted).toBe(false);
      expect(await operation.completion).toBe("cancelled");
      expect(fetchApiResource).not.toHaveBeenCalled();
    },
  );
  it.each(["", "other-resume"])(
    "does not POST without a usable revision after refreshing %s",
    async (refreshResume) => {
      vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
        session: { ...session(), revision: "" },
        run: null,
      });
      vi.mocked(loadAgentSession).mockResolvedValue(
        refreshResume ? session(refreshResume) : { ...session(), revision: "" },
      );
      const hook = mountConversation();
      await advance();
      let operation!: ReturnType<typeof hook.result.current.sendPrompt>;
      act(() => {
        operation = hook.result.current.sendPrompt("missing revision");
      });
      await advance(1000);
      expect(await operation.accepted).toBe(false);
      expect(await operation.completion).toBe("failed");
      expect(fetchApiResource).not.toHaveBeenCalled();
      expect(hook.result.current.requestPhase).toBe("idle");
    },
  );
  it("ignores an old terminal refresh failure after a new resume is ready", async () => {
    const refresh = deferred<AgentSessionResponse>();
    vi.mocked(loadAgentSession).mockReturnValue(refresh.promise);
    const hook = mountConversation();
    await advance();
    act(() => {
      hook.result.current.sendPrompt("old resume request");
    });
    await advance(420);
    expect(loadAgentSession).toHaveBeenCalledWith("resume-1");
    hook.rerender({ ...hook.props, resumeId: "resume-2" });
    await advance();
    await act(async () => refresh.reject(new Error("old refresh failed")));
    await advance();
    expect(hook.result.current).toMatchObject({
      isSessionReady: true,
      sessionLoadError: false,
      status: "ready",
    });
    expect(hook.result.current.messages.map(({ id }) => id)).toEqual([
      "history-resume-2",
    ]);
  });
  it.each([undefined, "resume-1"])(
    "sends canonical file-only turns with document language and correct prior history for %s",
    async (resumeId) => {
      const hook = mountConversation({ resumeId, documentLocale: "zh" });
      await advance();
      const prior = [
        { id: "prior-user", role: "user" as const, text: "Earlier user" },
        {
          id: "prior-assistant",
          role: "assistant" as const,
          text: "Earlier reply",
          response: {
            id: "prior-assistant",
            role: "assistant" as const,
            text: "Earlier reply",
          },
        },
      ];
      const files = [{ id: "attachment", filename: "resume.pdf" }];
      let operation!: ReturnType<typeof hook.result.current.sendPrompt>;
      act(() => {
        operation = hook.result.current.sendPrompt("   ", files, {
          baseMessages: prior,
          messageId: "file-only",
        });
      });
      await advance(420);
      expect(await operation.completion).toBe("completed");
      const body = JSON.parse(
        String(vi.mocked(fetchApiResource).mock.calls[0][1]?.body),
      );
      expect(body.message).toEqual({
        id: "file-only",
        role: "user",
        text: "",
        files,
      });
      expect(body.messages).toEqual(resumeId ? [] : prior);
      expect(body.locale).toBe("zh");
      expect(body.expectedRevision).toBe(
        resumeId ? "resume-1-revision" : undefined,
      );
      for (const field of [
        "prompt",
        "files",
        "conversation",
        "clientTurnId",
        "settings",
      ])
        expect(body).not.toHaveProperty(field);
    },
  );
  it("releases rejected preflight and permits a subsequent request", async () => {
    const hook = mountConversation({
      onBeforeSend: vi
        .fn()
        .mockRejectedValueOnce(new Error("preference flush failed"))
        .mockResolvedValue(undefined),
    });
    await advance();
    let first!: ReturnType<typeof hook.result.current.sendPrompt>;
    act(() => {
      first = hook.result.current.sendPrompt("failed preflight");
    });
    const rejected = expect(first.completion).rejects.toThrow(
      "preference flush failed",
    );
    await advance();
    expect(await first.accepted).toBe(false);
    await rejected;
    expect(hook.result.current.requestPhase).toBe("idle");
    expect(hook.result.current.messages.map(({ text }) => text)).toEqual([
      "persisted",
    ]);
    act(() => {
      hook.result.current.sendPrompt("retry");
    });
    await advance(420);
    expect(fetchApiResource).toHaveBeenCalledTimes(1);
  });
  it("keeps model selection frozen across preference waiting and rejects a concurrent send", async () => {
    const flush = deferred<void>();
    const post = deferred<Response>();
    vi.mocked(fetchApiResource).mockReturnValue(post.promise);
    const hook = mountConversation({ onBeforeSend: () => flush.promise });
    await advance();
    let first!: ReturnType<typeof hook.result.current.sendPrompt>;
    let duplicate!: typeof first;
    act(() => {
      first = hook.result.current.sendPrompt("first");
      duplicate = hook.result.current.sendPrompt("duplicate");
    });
    hook.rerender({
      ...hook.props,
      selectedModelConfig: { ...model, id: "model-2" },
    });
    await act(async () => {
      flush.resolve();
    });
    await advance(420);
    expect(await duplicate.accepted).toBe(false);
    expect(await duplicate.completion).toBe("cancelled");
    expect(fetchApiResource).toHaveBeenCalledTimes(1);
    const body = JSON.parse(
      String(vi.mocked(fetchApiResource).mock.calls[0][1]?.body),
    );
    expect(body).toMatchObject({
      modelConfig: { id: "model-1" },
      expectedRevision: "resume-1-revision",
      message: { text: "first" },
    });
    expect(body.modelConfig).toEqual({ id: "model-1" });
    expect(hook.result.current.requestPhase).toBe("preparing");
    await act(async () => {
      post.resolve(completedResponse());
      await first.completion;
    });
    expect(await first.accepted).toBe(true);
    expect(hook.result.current.requestPhase).toBe("idle");
    expect(hook.result.current.streamingMessage).toBeNull();
  });
  it("restores pre-send messages when stopping the owned debounce", async () => {
    const hook = mountConversation();
    await advance();
    let operation!: ReturnType<typeof hook.result.current.sendPrompt>;
    act(() => {
      operation = hook.result.current.sendPrompt("provisional");
    });
    await advance();
    expect(hook.result.current.messages.map(({ text }) => text)).toEqual([
      "persisted",
      "provisional",
    ]);
    act(() => hook.result.current.stopResponding());
    await advance(420);
    expect(await operation.completion).toBe("cancelled");
    expect(hook.result.current.messages.map(({ text }) => text)).toEqual([
      "persisted",
    ]);
    expect(fetchApiResource).not.toHaveBeenCalled();
  });
  it("does not roll a late failed send back over an adopted authoritative history", async () => {
    const post = deferred<Response>();
    vi.mocked(fetchApiResource).mockReturnValue(post.promise);
    const hook = mountConversation();
    await advance();
    act(() => {
      hook.result.current.sendPrompt("provisional");
    });
    await advance(420);
    await act(async () =>
      hook.result.current.runAgentDraftDecision(async () =>
        session("resume-1", "server-authoritative"),
      ),
    );
    vi.mocked(loadAgentSession).mockRejectedValue(
      new Error("refresh unavailable"),
    );
    await act(async () => {
      post.reject(new Error("late network failure"));
    });
    await advance();
    expect(hook.result.current.messages.map(({ text }) => text)).toEqual([
      "server-authoritative",
    ]);
    expect(hook.result.current.requestPhase).toBe("idle");
  });
  it("sends the loaded history revision and reconciles a failed replacement conflict", async () => {
    vi.mocked(replaceAgentSession).mockRejectedValue(
      Object.assign(new Error("conflict"), {
        apiCode: "AGENT_SESSION_REVISION_CONFLICT",
        status: 409,
      }),
    );
    vi.mocked(loadAgentSession).mockResolvedValue(
      session("resume-1", "server-authoritative"),
    );
    const hook = mountConversation();
    await advance();
    let operation!: ReturnType<typeof hook.result.current.sendPrompt>;
    act(() => {
      operation = hook.result.current.sendPrompt("edited", [], {
        replaceSessionBeforeSend: true,
        baseMessages: [{ id: "earlier", role: "user", text: "Keep earlier" }],
      });
    });
    await advance(420);
    expect(await operation.completion).toBe("failed");
    expect(replaceAgentSession).toHaveBeenCalledExactlyOnceWith(
      "resume-1",
      expect.objectContaining({
        revision: "resume-1-revision",
        locale: "en",
        messages: [
          { id: "earlier", role: "user", text: "Keep earlier" },
          expect.objectContaining({ text: "edited" }),
        ],
      }),
    );
    expect(fetchApiResource).not.toHaveBeenCalled();
    expect(hook.result.current.messages.map(({ text }) => text)).toEqual([
      "server-authoritative",
    ]);
    expect(hook.props.onRollbackAgentDraft).toHaveBeenCalled();
  });
  it.each(["completed", "cancelled"])(
    "keeps a durable %s message when terminal refresh fails and closes the send gate",
    async (status) => {
      vi.mocked(fetchApiResource).mockImplementation(async () =>
        completedResponse(status),
      );
      vi.mocked(loadAgentSession).mockRejectedValue(
        new Error("refresh failed"),
      );
      const hook = mountConversation();
      await advance();
      act(() => {
        hook.result.current.sendPrompt("prompt");
      });
      await advance(420);
      expect(
        hook.result.current.visibleMessages.map(({ text }) => text),
      ).toContain("kept partial");
      expect(hook.result.current).toMatchObject({
        isSessionReady: false,
        sessionLoadError: true,
        status: "error",
        requestPhase: "idle",
        streamingMessage: null,
      });
    },
  );
});

describe("Agent attachment preparation", () => {
  it("uploads sequentially, aborts the current upload on Stop, and silently cleans already uploaded files", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        blob: async () => new Blob(["file content"]),
      })),
    );
    const first = deferred<Awaited<ReturnType<typeof uploadAgentAttachment>>>();
    const second =
      deferred<Awaited<ReturnType<typeof uploadAgentAttachment>>>();
    vi.mocked(uploadAgentAttachment)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const stopConversation = vi.fn();
    const sendPrompt = vi.fn();
    const hook = renderHook(() =>
      useAgentPromptActions({
        hasConfiguredModel: true,
        isRequestBusy: false,
        isSessionReady: true,
        resumeId: "resume-1",
        sessionResetVersion: 0,
        sendPrompt,
        stopConversation,
        t,
      }),
    );
    let submission!: Promise<void>;
    act(() => {
      submission = hook.result.current.submitPrompt({
        text: "attachments",
        files: ["first", "second"].map((name) => ({
          type: "file",
          filename: `${name}.txt`,
          mediaType: "text/plain",
          url: `data:text/plain,${name}`,
        })),
      });
      hook.result.current.stopResponding();
    });
    expect(stopConversation).toHaveBeenCalledTimes(1);
    stopConversation.mockClear();
    const rejection = expect(submission).rejects.toMatchObject({
      name: "AbortError",
    });
    await advance();
    expect(uploadAgentAttachment).toHaveBeenCalledTimes(1);
    await expect(
      hook.result.current.submitPrompt({ text: "duplicate", files: [] }),
    ).rejects.toThrow("already in progress");
    act(() =>
      vi
        .mocked(uploadAgentAttachment)
        .mock.calls[0][2]?.onProgress?.({ loaded: 50, total: 100 }),
    );
    expect(hook.result.current.attachmentUploadProgress).toBe(25);
    await act(async () =>
      first.resolve({
        id: "first",
        filename: "first.txt",
        mediaType: "text/plain",
      }),
    );
    expect(uploadAgentAttachment).toHaveBeenCalledTimes(2);
    expect(hook.result.current.attachmentUploadProgress).toBe(50);
    act(() =>
      vi
        .mocked(uploadAgentAttachment)
        .mock.calls[1][2]?.onProgress?.({ loaded: 100, total: 100 }),
    );
    expect(hook.result.current.attachmentUploadProgress).toBe(99);
    expect(hook.result.current.isSubmittingPrompt).toBe(true);
    const signal = vi.mocked(uploadAgentAttachment).mock.calls[1][2]?.signal;
    act(() => hook.result.current.stopResponding());
    expect(signal?.aborted).toBe(true);
    expect(stopConversation).not.toHaveBeenCalled();
    await act(async () =>
      second.reject(new DOMException("stopped", "AbortError")),
    );
    await rejection;
    expect(deletePendingAgentAttachment).toHaveBeenCalledExactlyOnceWith(
      "resume-1",
      "first",
      { notifyOnError: false },
    );
    expect(sendPrompt).not.toHaveBeenCalled();
    expect(hook.result.current.isSubmittingPrompt).toBe(false);
    act(() => hook.result.current.stopResponding());
    expect(stopConversation).toHaveBeenCalledTimes(1);
  });
  it("routes Stop to the conversation after upload ownership is released even while submission completion is pending", async () => {
    const completion = deferred<"cancelled">();
    const sendPrompt = vi.fn(() => ({
      submitted: false,
      accepted: Promise.resolve(false),
      completion: completion.promise,
    }));
    const stopConversation = vi.fn();
    const hook = renderHook(() =>
      useAgentPromptActions({
        hasConfiguredModel: true,
        isRequestBusy: false,
        isSessionReady: true,
        resumeId: "resume-1",
        sessionResetVersion: 0,
        sendPrompt,
        stopConversation,
        t,
      }),
    );
    let submission!: Promise<void>;
    act(() => {
      submission = hook.result.current.submitPrompt({
        text: "prompt",
        files: [],
      });
    });
    const rejected = expect(submission).rejects.toThrow("not submitted");
    await advance();
    expect(hook.result.current.isSubmittingPrompt).toBe(true);
    act(() => hook.result.current.stopResponding());
    expect(stopConversation).toHaveBeenCalledTimes(1);
    await act(async () => completion.resolve("cancelled"));
    await rejected;
  });
});

describe("prompt snapshot boundaries", () => {
  it("intersects captured attachment ids with the current selection without adding new files", () => {
    const captured = [
      { id: "removed", filename: "removed.pdf" },
      { id: "captured", filename: "captured.pdf" },
    ];
    expect(
      selectActivePromptSubmissionFiles(captured, [
        { id: "captured" },
        { id: "new" },
      ]),
    ).toEqual([captured[1]]);
  });
  it.each([
    ["captured", true],
    ["new text", false],
  ] as const)(
    "clears captured text only while current text is %s",
    (current, expected) =>
      expect(shouldClearPromptSubmissionText("captured", current)).toBe(
        expected,
      ),
  );
  it.each(["conversion", "acceptance"])(
    "handles unmount during %s without losing the owned cleanup boundary",
    async (stage) => {
      const conversion = deferred<Response>();
      const acceptance = deferred<void>();
      const onSubmit = vi.fn(() => acceptance.promise);
      vi.stubGlobal(
        "fetch",
        vi.fn(() => conversion.promise),
      );
      vi.stubGlobal(
        "URL",
        class extends URL {
          static createObjectURL = vi.fn(() => "blob:captured");
          static revokeObjectURL = vi.fn();
        },
      );
      let hideForm!: () => void;
      let retainedController!: ReturnType<typeof usePromptInputController>;
      function ComposerProbe() {
        const controller = usePromptInputController();
        useLayoutEffect(() => {
          retainedController = controller;
        }, [controller]);
        return null;
      }
      const Wrapper = ({ children }: PropsWithChildren) => {
        const [mounted, setMounted] = useState(true);
        useLayoutEffect(() => {
          hideForm = () => setMounted(false);
        }, []);
        return (
          <PromptInputProvider initialInput="captured">
            <ComposerProbe />
            {mounted ? children : null}
          </PromptInputProvider>
        );
      };
      const hook = renderHook(
        () => ({
          controller: usePromptInputController(),
          form: usePromptInputForm({ onSubmit }),
        }),
        { wrapper: Wrapper },
      );
      act(() =>
        hook.result.current.controller.attachments.add([
          new File(["captured"], "captured.pdf"),
        ]),
      );
      let submission: void;
      act(() => {
        submission = hook.result.current.form.handleSubmit({
          preventDefault: vi.fn(),
          currentTarget: document.createElement("form"),
        } as unknown as FormEvent<HTMLFormElement>);
      });
      if (stage === "conversion") hook.unmount();
      await act(async () =>
        conversion.reject(new Error("conversion unavailable")),
      );
      if (stage === "conversion") {
        expect(onSubmit).not.toHaveBeenCalled();
        return;
      }
      expect(onSubmit).toHaveBeenCalledExactlyOnceWith(
        {
          text: "captured",
          files: [
            {
              type: "file",
              filename: "captured.pdf",
              mediaType: "",
              url: "blob:captured",
            },
          ],
        },
        expect.anything(),
      );
      const revoke = vi.mocked(URL.revokeObjectURL);
      revoke.mockClear();
      act(hideForm);
      revoke.mockClear();
      await act(async () => {
        acceptance.resolve();
        await submission;
      });
      expect(revoke).toHaveBeenCalledWith("blob:captured");
      expect(retainedController.attachments.files).toEqual([]);
      expect(retainedController.textInput.value).toBe("");
    },
  );
});
