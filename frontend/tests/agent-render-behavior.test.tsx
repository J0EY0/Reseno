import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { createRef, type ComponentProps } from "react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { PromptInputProvider } from "@/components/ai-elements/prompt-input-context";
import { AgentAssistantResponse } from "@/components/copilot/copilot-assistant-response";
import {
  AgentDraftReviewDock,
  type AgentDraftReviewDockView,
} from "@/components/copilot/agent-draft-review-dock";
import { AgentChangeSummary } from "@/components/copilot/copilot-change-summary";
import { CopilotComposer } from "@/components/copilot/copilot-composer";
import { CopilotConversationView } from "@/components/copilot/copilot-conversation-view";
import { CopilotModelSelector } from "@/components/copilot/copilot-model-selector";
import { CopilotPanel } from "@/components/copilot/copilot-panel";
import { AgentAssistantMessageRow } from "@/components/copilot/copilot-message-presentation";
import { TooltipProvider } from "@/components/ui/tooltip";
import { defaultMessages as t, loadMessages } from "@/i18n";
import { isPlainAgentText } from "@/lib/agent-message-rendering";
import {
  loadAgentSession,
  loadAgentSessionRecovery,
} from "@/lib/agent-session-run-client";
import { createDefaultModelConfig } from "@/lib/model-config";
import { createEmptyResume } from "@/lib/resume";
import type { AgentChatMessage, AgentSessionResponse } from "@/types/api";
import type { AgentPanelMessage } from "@/components/copilot/copilot-message-model";
import { toast } from "sonner";

const originalScrollIntoView = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "scrollIntoView",
);
const rendererLoad = vi.hoisted(() => ({
  ready: Promise.withResolvers<void>(),
  loaded: Promise.withResolvers<void>(),
}));
vi.mock("@/components/ai-elements/message-response", async (original) => {
  await rendererLoad.ready.promise;
  const module = await original();
  rendererLoad.loaded.resolve();
  return module;
});
vi.mock("@/lib/agent-session-run-client", () => ({
  loadAgentSession: vi.fn(),
  loadAgentSessionRecovery: vi.fn(),
  replaceAgentSession: vi.fn(),
  stopAgentRun: vi.fn(),
}));
vi.mock("@/lib/agent-attachment-client", () => ({
  uploadAgentAttachment: vi.fn(),
  deletePendingAgentAttachment: vi.fn(),
  downloadAgentAttachment: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { info: vi.fn(), error: vi.fn() } }));

const model = createDefaultModelConfig("en", {
  id: "model-1",
  model: "gpt-one",
  nickname: "First model",
  provider: "openai",
  supportsTools: true,
});
const otherModel = {
  ...model,
  id: "model-2",
  model: "gpt-two",
  nickname: "Second model",
};
function session(
  messages: AgentSessionResponse["messages"] = [],
): AgentSessionResponse {
  return {
    resumeId: "resume-1",
    revision: "revision-1",
    messages,
    executions: [],
  };
}
function promptActions(): ComponentProps<
  typeof CopilotComposer
>["promptActions"] {
  return {
    attachmentUploadProgress: null,
    isSubmittingPrompt: false,
    promptAttachmentCapacity: 5,
    referenceHistoryAttachment: vi.fn(),
    referencedAttachments: [],
    removeReferencedAttachment: vi.fn(),
    setPromptLocalAttachmentCount: vi.fn(),
    stopResponding: vi.fn(),
    submitPrompt: vi.fn(),
  };
}
function panelProps(): ComponentProps<typeof CopilotPanel> {
  return {
    isPanelCollapsed: false,
    resumeId: "resume-1",
    t,
    documentLocale: "en",
    resume: createEmptyResume(),
    modelConfigs: [model, otherModel],
    selectedModelConfigId: model.id,
    onSelectedModelConfigChange: vi.fn(),
    agentDraftState: null,
    agentDraftReview: null,
    onPreviewAgentEdits: vi.fn(),
    onReconcileAgentDraft: vi.fn(),
    onRollbackAgentDraft: vi.fn(),
    onApplyAgentDraft: vi.fn(async () => null),
    onDiscardAgentDraft: vi.fn(async () => null),
    onOpenModelSettings: vi.fn(),
    onStatusChange: vi.fn(),
  };
}
function conversationProps(
  messages: AgentPanelMessage[],
): ComponentProps<typeof CopilotConversationView> {
  return {
    conversation: {
      applyAgentDraft: vi.fn(),
      discardAgentDraft: vi.fn(),
      runAgentDraftDecision: vi.fn(),
      isSessionReady: true,
      messages,
      requestPhase: "idle",
      retrySession: vi.fn(),
      sessionLoadError: false,
      sessionResetVersion: 0,
      status: "ready",
      stopResponding: vi.fn(),
      streamingMessage: null,
      visibleMessages: messages,
      sendPrompt: vi.fn(),
    },
    conversationContextRef: createRef(),
    hasConfiguredModel: true,
    messageActions: {
      copiedMessageId: null,
      editingMessageId: null,
      editingMessageText: "",
      cancelEditingUserMessage: vi.fn(),
      copyUserMessage: vi.fn(),
      downloadHistoryAttachment: vi.fn(),
      setEditingMessageText: vi.fn(),
      retryUserMessage: vi.fn(),
      startEditingUserMessage: vi.fn(),
      submitEditedUserMessage: vi.fn(),
    },
    onOpenModelSettings: vi.fn(),
    promptActions: promptActions(),
    t,
  };
}
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <TooltipProvider>{children}</TooltipProvider>
);
beforeAll(async () => {
  await loadMessages("zh");
});
beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    })),
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
  vi.mocked(loadAgentSessionRecovery).mockResolvedValue({
    session: session(),
    run: null,
  });
  vi.mocked(loadAgentSession).mockResolvedValue(session());
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  if (originalScrollIntoView)
    Object.defineProperty(
      HTMLElement.prototype,
      "scrollIntoView",
      originalScrollIntoView,
    );
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});

describe("Agent response rendering", () => {
  it.each([
    ["根据招聘信息，这个岗位主要要求如下。", true],
    ["**核心职责**\n负责将 AI 能力落地到产品。", false],
    ["这里是 **重点** 内容。", false],
    ["使用 `React` 和 TypeScript。", false],
    ["- 核心职责", false],
    ["熟悉 A* 搜索算法。", true],
  ] as const)("classifies lightweight text %s", (text, expected) =>
    expect(isPlainAgentText(text)).toBe(expected),
  );
  it("keeps settled plain text visible and streaming fallback hidden until the real rich renderer loads", async () => {
    const view = render(
      <>
        <AgentAssistantResponse
          t={t}
          text="Settled plain response"
          sources={undefined}
        />
        <AgentAssistantResponse
          t={t}
          isStreaming
          text="Streaming response"
          sources={undefined}
        />
        <AgentAssistantResponse
          t={t}
          text="**Settled formatted response**"
          sources={undefined}
        />
      </>,
    );
    expect(screen.getByText("Settled plain response").tagName).toBe("P");
    expect(
      screen
        .getByText("Settled plain response")
        .classList.contains("invisible"),
    ).toBe(false);
    expect(
      screen.getByText("Streaming response").classList.contains("invisible"),
    ).toBe(true);
    expect(
      screen
        .getByText("**Settled formatted response**")
        .classList.contains("invisible"),
    ).toBe(false);
    await act(async () => {
      rendererLoad.ready.resolve();
      await rendererLoad.loaded.promise;
      await vi.dynamicImportSettled();
    });
    expect(
      view.container.querySelector(".agent-streaming-response"),
    ).not.toBeNull();
    expect(
      view.container.querySelector(".agent-streaming-response")?.textContent,
    ).toBe("Streaming response");
    expect(
      screen
        .getByText("Settled formatted response")
        .getAttribute("data-streamdown"),
    ).toBe("strong");
    expect(view.container.querySelector(".invisible")).toBeNull();
  });
  it("deduplicates valid web sources into a single tail citation with a hover carousel and no excerpts", async () => {
    render(
      <AgentAssistantResponse
        t={t}
        text="Answer with evidence"
        sources={[
          {
            id: "one",
            title: "Primary source",
            sourceType: "web",
            url: "https://example.com/job",
            excerpt: "private excerpt",
          },
          {
            id: "duplicate",
            title: "Duplicate source",
            sourceType: "web",
            url: "https://example.com/job",
          },
          {
            id: "two",
            title: "Second source",
            sourceType: "web",
            url: "https://other.test/job",
          },
          {
            id: "attachment",
            title: "Local attachment",
            sourceType: "attachment",
          },
          {
            id: "unsafe",
            title: "Unsafe URL",
            sourceType: "web",
            url: "javascript:alert(1)",
          },
        ]}
      />,
      { wrapper },
    );
    const pill = screen.getByText("example.com +1");
    expect(
      screen.getByText("Answer with evidence").classList.contains("inline"),
    ).toBe(true);
    expect(screen.queryByText("Primary source")).toBeNull();
    fireEvent.pointerEnter(pill, { pointerType: "mouse" });
    expect(await screen.findByText("Primary source")).toBeTruthy();
    expect(screen.getByText("Second source")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: t.agentNextSource }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: t.agentPreviousSource }),
    ).toBeTruthy();
    for (const text of [
      "Duplicate source",
      "private excerpt",
      "Local attachment",
      "Unsafe URL",
    ])
      expect(screen.queryByText(text)).toBeNull();
    expect(document.querySelector("citation")).toBeNull();
  });
  it("keeps continuation feedback after a completed tool in an active timeline", () => {
    const response: AgentChatMessage = {
      id: "assistant",
      role: "assistant",
      text: "",
      timeline: [{ id: "tools", type: "tool_group", toolIds: ["fetch"] }],
      tools: [
        {
          id: "fetch",
          title: "web_fetch",
          type: "tool-web_fetch",
          state: "output-available",
        },
      ],
    };
    const props = {
      t,
      isStreamingAssistant: true,
      message: {
        id: response.id,
        role: "assistant" as const,
        text: "",
        response,
      },
    };
    const view = render(<AgentAssistantMessageRow {...props} />, { wrapper });
    expect(screen.getByText(t.agentToolContinuing)).toBeTruthy();
    view.rerender(
      <AgentAssistantMessageRow {...props} isStreamingAssistant={false} />,
    );
    expect(screen.queryByText(t.agentToolContinuing)).toBeNull();
  });
  it("keeps all six pending decisions reachable through the composer dock", async () => {
    const dock: AgentDraftReviewDockView = {
      conflicts: [],
      disabled: false,
      hasScopeConflicts: false,
      mode: "all",
      onApply: vi.fn(),
      onApplyOriginal: vi.fn(),
      onDiscard: vi.fn(),
      onKeepManual: vi.fn(),
      onNext: vi.fn(),
      onPrevious: vi.fn(),
      onSelectFirst: vi.fn(),
      onShowAll: vi.fn(),
      pendingCount: 6,
      selectedIndex: 0,
      resolvingStatus: null,
    };
    const view = render(<AgentDraftReviewDock view={dock} t={t} />);
    expect(
      screen.getByText(t.agentReviewRemaining.replace("{count}", "6")),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: t.agentReviewOneByOne }),
    );
    expect(dock.onSelectFirst).toHaveBeenCalledOnce();
    view.rerender(
      <AgentDraftReviewDock
        view={{ ...dock, mode: "single", selectedIndex: 5 }}
        t={t}
      />,
    );
    expect(
      await screen.findByText(
        t.agentReviewSinglePosition
          .replace("{current}", "6")
          .replace("{total}", "6"),
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: t.agentReviewNext }));
    expect(dock.onNext).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: t.agentApplyThis }));
    expect(dock.onApply).toHaveBeenCalledOnce();
  });
  it("shows all resolved review counts and advisory warnings without exposing pending decisions in history", () => {
    const base: AgentChatMessage = {
      id: "summary",
      role: "assistant",
      text: "",
      transactionState: "committed",
      draft: {
        baseResume: createEmptyResume(),
        reviewItems: Array.from({ length: 6 }, (_, index) => ({
          id: `review-${index}`,
          editIds: [`edit-${index}`],
          status: index < 5 ? "applied" : "discarded",
        })),
      },
      tools: [
        {
          id: "edit",
          title: "edit_execute",
          type: "tool-edit_execute",
          state: "output-available",
          output: {
            qualityIssues: [
              {
                code: "unsupported_edit_claim",
                severity: "warning",
                target: "basic.summary",
              },
            ],
          },
        },
      ],
    };
    const view = render(<AgentChangeSummary response={base} t={t} />);
    expect(
      screen.getByText(
        t.agentDraftResolutionReceipt
          .replace("{applied}", "5")
          .replace("{discarded}", "1"),
      ),
    ).toBeTruthy();
    expect(screen.getByText(t.agentQualityUnsupportedClaim)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    const pending = {
      ...base,
      draft: {
        ...base.draft!,
        reviewItems: base.draft!.reviewItems.map((item) => ({
          ...item,
          status: "pending" as const,
        })),
      },
    };
    view.rerender(<AgentChangeSummary response={pending} t={t} />);
    expect(
      view.container.querySelector(
        '[data-slot="agent-draft-resolution-receipt"]',
      ),
    ).toBeNull();
    expect(screen.getByText(t.agentQualityUnsupportedClaim)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    view.rerender(
      <AgentChangeSummary
        response={{ ...base, transactionState: "rolled_back" }}
        t={t}
      />,
    );
    expect(view.container.textContent).toBe("");
  });
});

describe("Agent conversation presentation", () => {
  it("grants Retry only to the latest failed user even after a partial assistant response", () => {
    const messages: AgentPanelMessage[] = [
      "old-user",
      "assistant",
      "current-user",
      "partial",
    ].map((id, index) => ({
      id,
      role: index % 2 === 0 ? "user" : "assistant",
      text: id,
      ...(index % 2 === 0
        ? {
            execution: {
              runId: `run-${id}`,
              turnId: id,
              status: "failed" as const,
              errorCode: "AGENT_PROVIDER_TIMEOUT" as const,
              modelSnapshot: null,
              startedAt: "2026-01-01",
              completedAt: "2026-01-02",
            },
          }
        : {}),
    }));
    messages[2].files = [
      { id: "attached", filename: "resume.pdf", mediaType: "application/pdf" },
    ];
    const props = conversationProps(messages);
    const view = render(<CopilotConversationView {...props} />, { wrapper });
    const retry = screen.getByRole("button", { name: t.agentRetry });
    expect(
      within(screen.getByText("current-user").closest(".is-user")!).getByRole(
        "button",
        { name: t.agentRetry },
      ),
    ).toBe(retry);
    fireEvent.click(retry);
    expect(
      props.messageActions.retryUserMessage,
    ).toHaveBeenCalledExactlyOnceWith(messages[2]);
    expect(screen.getByText("resume.pdf")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText("AGENT_PROVIDER_TIMEOUT")).toBeNull();
    view.rerender(
      <CopilotConversationView {...conversationProps([messages[1]])} />,
    );
    expect(screen.queryByRole("button", { name: t.agentRetry })).toBeNull();
  });
  it("keeps session failure visible with retained history and offers retry", () => {
    const props = conversationProps([
      { id: "history", role: "user", text: "Saved history" },
    ]);
    props.conversation.sessionLoadError = true;
    props.conversation.isSessionReady = false;
    render(<CopilotConversationView {...props} />, { wrapper });
    expect(screen.getByRole("alert").textContent).toContain(
      t.agentHistoryLoadFailed,
    );
    expect(screen.getByText("Saved history")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: t.agentRetry }));
    expect(props.conversation.retrySession).toHaveBeenCalledTimes(1);
  });
  it("renders the newest ten messages then prepends six per frame without trimming source history", () => {
    vi.useFakeTimers({
      toFake: ["requestAnimationFrame", "cancelAnimationFrame"],
    });
    const messages: AgentPanelMessage[] = Array.from(
      { length: 24 },
      (_, index) => ({
        id: `history-${index}`,
        role: "user",
        text: `History row ${index}`,
      }),
    );
    const props = conversationProps(messages);
    const view = render(<CopilotConversationView {...props} />, { wrapper });
    const texts = () =>
      screen.getAllByText(/^History row/).map((node) => node.textContent);
    expect(texts()).toEqual(messages.slice(14).map(({ text }) => text));
    for (const first of [8, 2, 0]) {
      act(() => vi.advanceTimersToNextFrame());
      expect(texts()).toEqual(messages.slice(first).map(({ text }) => text));
    }
    expect(props.conversation.messages).toHaveLength(24);
    expect(screen.getByRole("log").getAttribute("aria-busy")).toBe("false");
    view.unmount();
  });
});

describe("Agent model and composer controls", () => {
  it.each(["preparing", "responding"] as const)(
    "keeps model and attachment staging available during %s while disabling send text",
    (requestPhase) => {
      const props: ComponentProps<typeof CopilotComposer> = {
        globalDropActive: true,
        hasConversationHistory: true,
        isSessionReady: true,
        modelConfigs: [model],
        onOpenModelSettings: vi.fn(),
        onSelectedModelConfigChange: vi.fn(),
        promptActions: promptActions(),
        requestPhase,
        selectedModelConfig: model,
        selectedModelConfigId: model.id,
        t,
      };
      const content = (current: typeof props) => (
        <PromptInputProvider>
          <CopilotComposer {...current} />
        </PromptInputProvider>
      );
      const view = render(content(props), { wrapper });
      const textarea = screen.getByRole("textbox", {
        name: t.agentPromptPlaceholderShort,
      }) as HTMLTextAreaElement;
      expect(textarea.disabled).toBe(true);
      expect(textarea.placeholder).toBe("");
      expect(
        (
          screen.getByRole("button", {
            name: t.agentAddAttachments,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false);
      expect(
        (screen.getByTitle(model.model) as HTMLButtonElement).disabled,
      ).toBe(false);
      expect(
        screen.getByTitle(model.model).querySelector("span:last-child")
          ?.textContent,
      ).toBe("GPT-ONE");
      view.rerender(
        content({
          ...props,
          promptActions: {
            ...props.promptActions,
            isSubmittingPrompt: true,
            attachmentUploadProgress: 99,
          },
        }),
      );
      expect(
        (screen.getByTitle(model.model) as HTMLButtonElement).disabled,
      ).toBe(true);
      expect(
        (
          screen.getByRole("button", {
            name: t.agentAddAttachments,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true);
      expect(screen.getByText("99%")).toBeTruthy();
      fireEvent.click(
        screen.getByRole("button", {
          name: t.agentAttachmentUploading.replace("{progress}", "99"),
        }),
      );
      expect(props.promptActions.stopResponding).toHaveBeenCalledTimes(1);
      view.rerender(
        content({ ...props, isSessionReady: false, requestPhase: "idle" }),
      );
      expect(
        (screen.getByRole("textbox") as HTMLTextAreaElement).disabled,
      ).toBe(true);
      expect(
        (
          screen.getByRole("button", {
            name: t.agentAddAttachments,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true);
    },
  );
  it.each([
    { busy: true, changed: true },
    { busy: true, changed: false },
    { busy: false, changed: true },
  ])(
    "announces model changes only for a changed next turn: %j",
    async ({ busy, changed }) => {
      const onChange = vi.fn();
      render(
        <CopilotModelSelector
          appliesToNextMessage={busy}
          disabled={false}
          modelConfigs={[model, otherModel]}
          onOpenModelSettings={vi.fn()}
          onSelectedModelConfigChange={onChange}
          selectedModelConfig={model}
          selectedModelConfigId={model.id}
          t={t}
        />,
        { wrapper },
      );
      fireEvent.click(screen.getByTitle(model.model));
      fireEvent.click(
        await screen.findByRole("option", {
          name: new RegExp(changed ? otherModel.nickname : model.nickname),
        }),
      );
      expect(onChange).toHaveBeenCalledExactlyOnceWith(
        changed ? otherModel.id : model.id,
      );
      if (busy && changed)
        expect(toast.info).toHaveBeenCalledExactlyOnceWith(
          t.agentModelChangedNextTurn,
          { closeButton: true },
        );
      else expect(toast.info).not.toHaveBeenCalled();
      expect(
        screen.getByTitle(model.model).querySelector("span:last-child")
          ?.textContent,
      ).toBe("GPT-ONE");
    },
  );
  it("filters non-tool models without choosing a fallback and reports actual hydration status", async () => {
    const recovery =
      Promise.withResolvers<
        Awaited<ReturnType<typeof loadAgentSessionRecovery>>
      >();
    vi.mocked(loadAgentSessionRecovery).mockReturnValue(recovery.promise);
    const invalid = {
      ...model,
      id: "unsupported",
      nickname: "Unsupported model",
      supportsTools: false,
    };
    const props = {
      ...panelProps(),
      modelConfigs: [invalid, model],
      selectedModelConfigId: invalid.id,
    };
    render(<CopilotPanel {...props} />, { wrapper });
    expect(props.onStatusChange).toHaveBeenLastCalledWith("loading");
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).disabled).toBe(
      true,
    );
    await act(async () => recovery.resolve({ session: session(), run: null }));
    expect(props.onStatusChange).toHaveBeenLastCalledWith("ready");
    expect(screen.getByText(t.agentModelNotConfigured)).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: t.agentAddAttachments,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).disabled).toBe(
      true,
    );
    fireEvent.click(screen.getByTitle(t.agentModelConfigureHover));
    expect(
      await screen.findByRole("option", { name: /First model/ }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("option", { name: /Unsupported model/ }),
    ).toBeNull();
    expect(props.onSelectedModelConfigChange).not.toHaveBeenCalled();
  });
  it("disables the global attachment drop target when a retained panel collapses", async () => {
    vi.stubGlobal(
      "URL",
      class extends URL {
        static createObjectURL = vi.fn(() => "blob:dropped");
        static revokeObjectURL = vi.fn();
      },
    );
    const props = panelProps();
    const view = render(<CopilotPanel {...props} />, { wrapper });
    await waitFor(() =>
      expect(props.onStatusChange).toHaveBeenLastCalledWith("ready"),
    );
    const drop = (name: string) =>
      fireEvent.drop(document, {
        dataTransfer: {
          types: ["Files"],
          files: [new File(["text"], name, { type: "text/plain" })],
        },
      });
    drop("retained.txt");
    expect(screen.getByText("retained.txt")).toBeTruthy();
    view.rerender(<CopilotPanel {...props} isPanelCollapsed />);
    drop("hidden.txt");
    expect(screen.queryByText("hidden.txt")).toBeNull();
    expect(screen.getByText("retained.txt")).toBeTruthy();
    expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(1);
  });
});
