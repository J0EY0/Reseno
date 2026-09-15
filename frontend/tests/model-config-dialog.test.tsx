import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { defaultMessages as t } from "@/i18n";
import { ModelConfigFormPopover } from "@/components/model-config-form-popover";
import { useModelConfigDialog } from "@/components/models/use-model-config-dialog";
import { createDefaultModelConfig } from "@/lib/model-config";
import type { ModelProviderMeta } from "@/lib/model-providers";
import type { DiscoveredModel } from "@/lib/model-config-api";

const api = vi.hoisted(() => ({
  providers: vi.fn(),
  discover: vi.fn(),
  save: vi.fn(),
}));
vi.mock("@/lib/model-config-api", async (original) => ({
  ...(await original<typeof import("@/lib/model-config-api")>()),
  getModelProviders: api.providers,
  discoverModels: api.discover,
  saveModelConfig: api.save,
}));
const provider: ModelProviderMeta = {
  id: "openai",
  kind: "cloud",
  label: "OpenAI",
  iconProvider: "openai",
  defaultBaseUrl: " https://api.openai.com/v1 ",
  authRequired: false,
  apiFamily: "openai_responses",
  officialUrl: "",
  supportsModelDiscovery: true,
  supportsCustomCapabilities: false,
  supportsTools: true,
  supportsStreaming: true,
};
const model: DiscoveredModel = {
  id: "gpt-test",
  label: "GPT Test",
  contextWindowTokens: 128000,
  maxOutputTokens: 65536,
  supportsImage: true,
  supportsThinking: true,
  availableThinkingModes: ["auto", "off"],
  supportsTools: true,
  supportsStreaming: true,
  metadataSource: "provider",
};
const initial = {
  ...createDefaultModelConfig("en"),
  id: "saved",
  provider: "openai",
  providerKind: "cloud" as const,
  model: "saved-only",
  apiUrl: "https://stale.test/v1",
};
const options = {
  locale: "en",
  messages: t,
  mode: "create",
  onSaved: vi.fn(),
} as const;
beforeEach(() => {
  api.providers.mockReset().mockResolvedValue({ providers: [provider] });
  api.discover
    .mockReset()
    .mockResolvedValue({ models: [model], source: "cache" });
  api.save.mockReset().mockResolvedValue({ ...initial, model: "gpt-test" });
  vi.stubGlobal(
    "ResizeObserver",
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
    })),
  );
});
afterEach(() => vi.unstubAllGlobals());

it.each([false, true])(
  "keeps discovery provisional through provider loading and cache settlement, failure=%s",
  async (failure) => {
    const metadata = Promise.withResolvers<{
      providers: ModelProviderMeta[];
    }>();
    const discovered = Promise.withResolvers<{
      models: DiscoveredModel[];
      source: string;
    }>();
    api.providers.mockReturnValue(metadata.promise);
    api.discover.mockReturnValue(discovered.promise);
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() =>
      useModelConfigDialog({
        ...options,
        mode: "edit",
        initialConfig: initial,
      }),
    );
    expect(api.providers).toHaveBeenCalledOnce();
    expect(result.current.modelOptionsLoading).toBe(true);
    expect(api.discover).not.toHaveBeenCalled();
    await act(async () => metadata.resolve({ providers: [provider] }));
    expect(result.current.providersLoaded).toBe(true);
    expect(result.current.modelOptionsLoading).toBe(true);
    expect(api.discover).toHaveBeenCalledExactlyOnceWith({
      provider: "openai",
      apiFamily: "openai_responses",
      apiUrl: "https://api.openai.com/v1",
      configId: "saved",
    });
    await act(async () => {
      if (failure) discovered.reject(new Error("offline"));
      else discovered.resolve({ models: [model], source: "cache" });
    });
    expect(result.current.modelOptionsLoading).toBe(false);
    expect(result.current.draft.model).toBe(
      failure ? "saved-only" : "gpt-test",
    );
    expect(errorLog).toHaveBeenCalledTimes(failure ? 1 : 0);
  },
);
it.each([0, 1, 2])(
  "only auto-selects a single discovery result, count=%s",
  async (count) => {
    const models = Array.from({ length: count }, (_, index) => ({
      ...model,
      id: `model-${index}`,
    }));
    api.discover.mockResolvedValue({ models, source: "cache" });
    const { result } = renderHook(() => useModelConfigDialog(options));
    await waitFor(() => expect(result.current.modelOptionsLoading).toBe(false));
    expect(result.current.draft.model).toBe(count === 1 ? "model-0" : "");
    if (count > 1) {
      act(() => result.current.selectModel("model-1"));
      expect(result.current.draft.model).toBe("model-1");
    }
    await act(async () => result.current.refreshModels());
    expect(api.discover.mock.calls[0][0]).not.toHaveProperty("refresh");
    expect(api.discover.mock.calls[1][0]).toMatchObject({
      refresh: true,
      apiUrl: "https://api.openai.com/v1",
    });
  },
);
it("returns actual invalid fields without submitting to the server", async () => {
  api.providers.mockResolvedValue({
    providers: [{ ...provider, authRequired: true }],
  });
  const { result } = renderHook(() => useModelConfigDialog(options));
  await waitFor(() => expect(result.current.modelOptionsLoading).toBe(false));
  await act(async () =>
    expect(result.current.submit()).resolves.toEqual({
      status: "invalid",
      errors: { apiKey: t.validationRequired },
    }),
  );
  expect(api.save).not.toHaveBeenCalled();
});
it.each(["create", "edit"] as const)(
  "SSR exposes the concrete %s trigger as a closed dialog trigger",
  (mode) => {
    const markup = renderToStaticMarkup(
      <ModelConfigFormPopover
        locale="en"
        mode={mode}
        onSubmit={vi.fn()}
        t={t}
        trigger={mode === "edit" ? <button>Edit model</button> : undefined}
      />,
    );
    expect(markup).toContain('aria-haspopup="dialog"');
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).toContain(mode === "edit" ? "Edit model" : t.addModelConfig);
  },
);
it("loads a form only on first open and starts a fresh form after closing", async () => {
  render(
    <ModelConfigFormPopover
      locale="en"
      mode="create"
      onSubmit={vi.fn()}
      t={t}
    />,
  );
  expect(api.providers).not.toHaveBeenCalled();
  const trigger = screen.getByRole("button", { name: t.addModelConfig });
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(
      within(dialog)
        .getByRole("button", { name: t.createModelConfig })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.change(within(dialog).getByLabelText(t.nickname), {
    target: { value: "Unsaved nickname" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: t.cancel }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  fireEvent.click(trigger);
  const reopened = await screen.findByRole("dialog");
  await waitFor(() => expect(api.providers).toHaveBeenCalledTimes(2));
  expect(
    (within(reopened).getByLabelText(t.nickname) as HTMLInputElement).value,
  ).toBe("");
});
it("opens a triggerless edit form, focuses invalid controls and restores caller focus on close", async () => {
  api.providers.mockResolvedValue({
    providers: [{ ...provider, authRequired: true }],
  });
  const restoreFocus = vi.fn();
  render(
    <ModelConfigFormPopover
      locale="en"
      mode="edit"
      defaultOpen
      trigger={null}
      initialConfig={{ ...initial, apiKeyPreview: "" }}
      restoreFocus={restoreFocus}
      onSubmit={vi.fn()}
      t={t}
    />,
  );
  const dialog = await screen.findByRole("dialog");
  expect(screen.queryByRole("button", { name: t.addModelConfig })).toBeNull();
  const save = within(dialog).getByRole("button", { name: t.saveModelConfig });
  await waitFor(() => expect(save.hasAttribute("disabled")).toBe(false));
  fireEvent.click(save);
  await waitFor(() =>
    expect(document.activeElement).toBe(dialog.querySelector("#model-api-key")),
  );
  expect(api.save).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: t.cancel }));
  await waitFor(() => expect(restoreFocus).toHaveBeenCalledOnce());
});

it("keeps the closed dialog present until its exit animation finishes", async () => {
  const style = document.createElement("style");
  style.textContent =
    '[data-slot="dialog-content"][data-state="open"] { animation-name: enter; } [data-slot="dialog-content"][data-state="closed"] { animation-name: exit; }';
  document.head.append(style);
  try {
    render(
      <ModelConfigFormPopover
        locale="en"
        mode="create"
        onSubmit={vi.fn()}
        t={t}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: t.addModelConfig }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() =>
      expect(
        within(dialog)
          .getByRole("button", { name: t.createModelConfig })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent(
      dialog,
      Object.assign(new Event("animationstart", { bubbles: true }), {
        animationName: "enter",
      }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: t.cancel }));
    expect(dialog.isConnected).toBe(true);
    expect(dialog.getAttribute("data-state")).toBe("closed");
    fireEvent(
      dialog,
      Object.assign(new Event("animationend", { bubbles: true }), {
        animationName: "exit",
      }),
    );
    expect(dialog.isConnected).toBe(false);
  } finally {
    style.remove();
  }
});
