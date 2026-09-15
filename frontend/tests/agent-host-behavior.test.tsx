import { useLayoutEffect } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import { ResumeDetailHeaderActions } from "@/components/workspace/resume-detail-header-actions";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { useResumeDetailAgentLayout } from "@/components/workspace/use-resume-detail-agent-layout";
import { writeWorkspaceLayoutPreference } from "@/components/workspace/resume-workspace-layout";
import { defaultMessages as t, loadMessages } from "@/i18n";
import { fetchApiResource } from "@/lib/api-client";
import {
  loadAgentSession,
  loadAgentSessionRecovery,
} from "@/lib/agent-session-run-client";
import { createDefaultModelConfig } from "@/lib/model-config";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

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
  downloadAgentAttachment: vi.fn(),
}));

function workspace(): ResumeDetailWorkspaceModel {
  const item = createResumeDetailItem({ id: "resume-1", documentLocale: "zh" });
  const template = createResumeDetailTemplate("minimal");
  return {
    state: {
      activeTemplate: template,
      previewTemplate: template,
      previewTypography: item.typography,
      agent: {
        draft: null,
        draftState: null,
        isPanelCollapsed: true,
        modelConfigs: [
          createDefaultModelConfig("en", {
            id: "model-1",
            model: "test-model",
            nickname: "Test model",
            provider: "openai",
          }),
        ],
        panelStatus: null,
        review: null,
        selectedModelConfigId: "model-1",
      },
      openSectionId: null,
      document: { isPreviewReady: true, isSmartFittingOnePage: false },
      hasLoadError: false,
      hasVersionLoadError: false,
      hasTemplateStyleOverrides: false,
      isDuplicatingResume: false,
      isExporting: false,
      isLoading: false,
      leave: { isOpen: false, isResolving: false },
      previewResume: item.resume,
      previewReview: null,
      resolvedTheme: "light",
      resume: item.resume,
      resumeItem: item,
      save: {
        activeVersionId: null,
        changeCount: 0,
        lastSavedAt: null,
        state: "saved",
        versions: [],
      },
      showSkeleton: false,
      template: "minimal",
      templates: [template],
      theme: "light",
      title: { draft: item.title, isOpen: false },
      typography: item.typography,
    },
    commands: {
      agent: {
        applyDraft: vi.fn(async () => null),
        changeSelectedModelConfig: vi.fn(),
        discardDraft: vi.fn(async () => null),
        flushUserSettings: vi.fn(async () => undefined),
        openModelSettings: vi.fn(),
        previewEdits: vi.fn(),
        reconcileDraft: vi.fn(),
        reportPanelStatus: vi.fn(),
        rollbackDraft: vi.fn(),
        setPanelCollapsed: vi.fn(),
      },
      applyTemplate: vi.fn(),
      back: vi.fn(),
      changeTheme: vi.fn(),
      changeTitleDraft: vi.fn(),
      changeView: vi.fn(),
      duplicateResume: vi.fn(),
      exportImages: vi.fn(),
      exportJson: vi.fn(),
      exportPdf: vi.fn(),
      fitOnePage: vi.fn(),
      logout: vi.fn(),
      onPreviewReadyChange: vi.fn(),
      preloadView: vi.fn(),
      restoreTemplateDefaults: vi.fn(),
      retryLoad: vi.fn(),
      save: vi.fn(),
      saveAndReload: vi.fn(),
      saveTitle: vi.fn(),
      selectVersion: vi.fn(),
      addSection: vi.fn(),
      removeSection: vi.fn(),
      toggleSection: vi.fn(),
      updateContent: vi.fn(),
      setTitleDialogOpen: vi.fn(),
      updateTemplateSettings: vi.fn(),
      updateTypography: vi.fn(),
      cancelLeave: vi.fn(),
      discardAndLeave: vi.fn(),
      saveAndLeave: vi.fn(),
    },
  };
}
beforeAll(() => loadMessages("zh"));
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
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    })),
  );
  vi.mocked(loadAgentSession).mockResolvedValue({
    resumeId: "resume-1",
    revision: "updated",
    messages: [
      { id: "saved", role: "assistant", text: "Done", createdAt: "2026-01-01" },
    ],
    executions: [],
  });
  vi.mocked(fetchApiResource).mockImplementation(
    async () =>
      new Response(
        'id: 1\nevent: message_done\ndata: {"message":{"id":"saved","text":"Done"}}\n\nid: 2\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}\n\n',
        {
          headers: {
            "Content-Type": "text/event-stream",
            "X-Agent-Run-Id": "run-1",
          },
        },
      ),
  );
  writeWorkspaceLayoutPreference({ agentCollapsed: true });
});
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
  vi.doUnmock("@/components/copilot/copilot-panel");
});

it.each(["focus", "hover"])(
  "preloads on %s, retains one loading body through hydration, and preserves the inert collapsed panel",
  async (event) => {
    vi.resetModules();
    const panelLoad = {
      ready: Promise.withResolvers<void>(),
      started: vi.fn(),
      loading: Promise.withResolvers<void>(),
      loaded: Promise.withResolvers<void>(),
    };
    vi.doMock("@/components/copilot/copilot-panel", async (original) => {
      panelLoad.started();
      panelLoad.loading.resolve();
      await panelLoad.ready.promise;
      const module = await original();
      panelLoad.loaded.resolve();
      return module;
    });
    const { ResumeDetailAgentHost, ResumeDetailAgentToggle } =
      await import("@/components/workspace/resume-detail-agent-host");
    const recovery =
      Promise.withResolvers<
        Awaited<ReturnType<typeof loadAgentSessionRecovery>>
      >();
    const recoveryStarted = Promise.withResolvers<void>();
    vi.mocked(loadAgentSessionRecovery).mockImplementation(() => {
      recoveryStarted.resolve();
      return recovery.promise;
    });
    const base = workspace();
    let layout!: ReturnType<typeof useResumeDetailAgentLayout>;
    function Workspace() {
      const currentLayout = useResumeDetailAgentLayout("resume-1");
      useLayoutEffect(() => {
        layout = currentLayout;
      }, [currentLayout]);
      const model: ResumeDetailWorkspaceModel = {
        ...base,
        state: {
          ...base.state,
          agent: {
            ...base.state.agent,
            isPanelCollapsed: currentLayout.isPanelCollapsed,
            panelStatus: currentLayout.panelStatus,
          },
        },
        commands: {
          ...base.commands,
          agent: {
            ...base.commands.agent,
            setPanelCollapsed: currentLayout.setIsPanelCollapsed,
            reportPanelStatus: currentLayout.reportPanelStatus,
          },
        },
      };
      return (
        <>
          <ResumeDetailAgentToggle messages={t} model={model} />
          <ResumeDetailAgentHost messages={t} model={model} />
        </>
      );
    }
    const view = render(<Workspace />);
    const toggle = screen.getByRole("button", { name: t.agentExpandPanel });
    expect(view.container.querySelector("aside")).toBeNull();
    expect(panelLoad.started).not.toHaveBeenCalled();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.hasAttribute("aria-haspopup")).toBe(false);
    if (event === "focus") fireEvent.focus(toggle);
    else fireEvent.pointerEnter(toggle);
    await act(async () => panelLoad.loading.promise);
    expect(panelLoad.started).toHaveBeenCalledTimes(1);
    fireEvent.click(toggle);
    const dock = view.container.querySelector("aside")!;
    expect(dock.id).toBe(toggle.getAttribute("aria-controls"));
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const loader = () =>
      view.container.querySelectorAll('[data-slot="agent-panel-loading"]');
    const live = view.container.querySelector(
      '[data-slot="agent-panel-live-body"]',
    )!;
    expect(loader()).toHaveLength(1);
    expect(live.hasAttribute("inert")).toBe(true);
    await act(async () => {
      panelLoad.ready.resolve();
      await panelLoad.loaded.promise;
      await vi.dynamicImportSettled();
    });
    await act(async () => recoveryStarted.promise);
    expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(1);
    expect(loader()).toHaveLength(1);
    expect(live.getAttribute("aria-hidden")).toBe("true");
    await act(async () =>
      recovery.resolve({
        session: {
          resumeId: "resume-1",
          revision: "ready",
          messages: [],
          executions: [],
        },
        run: null,
      }),
    );
    await waitFor(() => expect(loader()).toHaveLength(0));
    expect(live.hasAttribute("inert")).toBe(false);
    expect(live.getAttribute("aria-hidden")).toBe("false");
    const input = screen.getByRole("textbox", {
      name: t.agentPromptPlaceholderShort,
    }) as HTMLTextAreaElement;
    fireEvent.change(input, {
      target: { value: "Keep this unfinished prompt" },
    });
    fireEvent.click(toggle);
    expect(dock.hasAttribute("inert")).toBe(true);
    expect(dock.getAttribute("aria-hidden")).toBe("true");
    act(() => layout.reportPanelStatus("responding"));
    expect(toggle.getAttribute("data-agent-status")).toBe("responding");
    expect(screen.getByRole("status").textContent).toBe(t.agentThinking);
    expect(
      view.container.querySelector('[data-slot="agent-status-indicator"]'),
    ).toBeNull();
    fireEvent.click(toggle);
    expect(
      screen.getByRole("textbox", { name: t.agentPromptPlaceholderShort }),
    ).toBe(input);
    expect(input.value).toBe("Keep this unfinished prompt");
    expect(loadAgentSessionRecovery).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: t.agentSendPrompt }));
    await waitFor(() => expect(fetchApiResource).toHaveBeenCalledTimes(1));
    expect(
      JSON.parse(String(vi.mocked(fetchApiResource).mock.calls[0][1]?.body))
        .locale,
    ).toBe("zh");
    expect(await screen.findByText("Done")).toBeTruthy();
  },
);

it.each(["loading", "ready", "responding", "error"] as const)(
  "does not expose a previous resume's %s status",
  (status) => {
    const hook = renderHook((id: string) => useResumeDetailAgentLayout(id), {
      initialProps: "resume-1",
    });
    const staleReport = hook.result.current.reportPanelStatus;
    act(() => staleReport(status));
    expect(hook.result.current.panelStatus).toBe(status);
    hook.rerender("resume-2");
    expect(hook.result.current.panelStatus).toBeNull();
    act(() => staleReport(status));
    expect(hook.result.current.panelStatus).toBeNull();
    act(() => hook.result.current.reportPanelStatus("ready"));
    expect(hook.result.current.panelStatus).toBe("ready");
  },
);

it.each([true, false])(
  "uses the compact actions menu to change collapsed=%s and presents the same status",
  async (collapsed) => {
    const model = workspace();
    model.state.agent.isPanelCollapsed = collapsed;
    model.state.agent.panelStatus = "responding";
    const view = render(
      <ResumeDetailHeaderActions
        compact
        locale="en"
        messages={t}
        model={model}
        onLocaleChange={vi.fn()}
      />,
    );
    expect(
      view.container
        .querySelector('[data-slot="agent-compact-status-indicator"]')
        ?.parentElement?.getAttribute("data-agent-status"),
    ).toBe("responding");
    fireEvent.keyDown(screen.getByRole("button", { name: t.actions }), {
      key: "Enter",
    });
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: collapsed ? t.agentExpandPanel : t.agentCollapsePanel,
      }),
    );
    expect(
      model.commands.agent.setPanelCollapsed,
    ).toHaveBeenCalledExactlyOnceWith(!collapsed);
  },
);
