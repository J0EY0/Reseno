import { fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { defaultMessages as t } from "@/i18n";
import { ModelConfigModelFields } from "@/components/models/model-config-model-fields";
import { ModelConfigProviderFields } from "@/components/models/model-config-provider-fields";
import {
  createModelConfigDraft,
  type ModelConfigDraft,
} from "@/components/models/model-config-draft";
import { focusFirstModelConfigError } from "@/components/models/model-config-focus";
import { AgentSettingsTab } from "@/components/agent-settings-tab";
import { Tabs } from "@/components/ui/tabs";
import { createDefaultModelConfig } from "@/lib/model-config";
import type { ModelConfigDialogController } from "@/components/models/use-model-config-dialog";
import type { ModelProviderMeta } from "@/lib/model-providers";
import type { DiscoveredModel } from "@/lib/model-config-api";

const cloud: ModelProviderMeta = {
  id: "openai",
  kind: "cloud",
  label: "OpenAI",
  iconProvider: "openai",
  defaultBaseUrl: "https://api.openai.com/v1",
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
function controller(
  draft: Partial<ModelConfigDraft> = {},
  overrides: Partial<ModelConfigDialogController> = {},
): ModelConfigDialogController {
  return {
    canDiscoverModels: true,
    discovering: false,
    discoveredModels: [model],
    draft: {
      ...createModelConfigDraft("en"),
      provider: "openai",
      providerKind: "cloud",
      apiFamily: "openai_responses",
      model: "gpt-test",
      maxTokens: "8192",
      contextWindowTokens: "128000",
      supportsThinking: true,
      availableThinkingModes: ["auto", "off"],
      ...draft,
    },
    errors: {},
    modelOptionsLoading: false,
    providers: [cloud],
    providersLoaded: true,
    refreshModels: vi.fn(async () => {}),
    selectModel: vi.fn(),
    selectProvider: vi.fn(),
    selectedProvider: cloud,
    submit: vi.fn(async () => ({ status: "saved" as const })),
    submitting: false,
    updateField: vi.fn(),
    ...overrides,
  };
}
function fields(value: ModelConfigDialogController) {
  return <ModelConfigModelFields controller={value} messages={t} />;
}
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
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});
afterEach(() => vi.unstubAllGlobals());

it("SSR keeps a provisional cloud model as skeletons until discovery settles", () => {
  const markup = renderToStaticMarkup(
    fields(controller({}, { modelOptionsLoading: true })),
  );
  expect(markup).toContain('data-slot="skeleton"');
  for (const value of [
    'id="model-select"',
    'id="model-output-settings"',
    "GPT Test",
  ])
    expect(markup).not.toContain(value);
});
it.each(["local", "custom"] as const)(
  "SSR preserves only applicable sampling inputs for %s",
  (providerKind) => {
    const markup = renderToStaticMarkup(
      fields(
        controller({
          providerKind,
          temperature: "0",
          topP: "0.75",
          maxTokens: "4096",
        }),
      ),
    );
    if (providerKind === "local") {
      expect(markup).toMatch(
        /id="model-temperature"[^>]*inputMode="decimal"[^>]*value="0"/,
      );
      expect(markup).toMatch(
        /id="model-top-p"[^>]*inputMode="decimal"[^>]*value="0.75"/,
      );
    } else
      expect(markup).not.toMatch(/id="model-temperature"|id="model-top-p"/);
  },
);
it("SSR renders the flat cloud output override and excludes provider-managed controls and removed copy", () => {
  const markup = renderToStaticMarkup(fields(controller()));
  expect(markup).toContain('id="model-output-settings"');
  expect(markup).toContain(t.advancedSettings);
  expect(markup).toMatch(
    /<input[^>]*type="text"[^>]*data-slot="input"[^>]*id="model-max-tokens"[^>]*inputMode="numeric"[^>]*placeholder="Auto"/,
  );
  expect(markup).not.toMatch(
    /model-thinking-enabled|Enable Thinking|model-context-window|model-temperature|model-top-p|Output length:|Leave blank for Auto|Model maximum:|rounded-lg border/,
  );
});
it.each([true, false])(
  "retains collapsed Auto settings when capability metadata is known=%s",
  (known) => {
    const markup = renderToStaticMarkup(
      fields(
        controller(
          { maxTokens: "" },
          { discoveredModels: known ? [model] : [] },
        ),
      ),
    );
    expect(markup).toContain('id="model-output-settings"');
    expect(markup).toContain(t.advancedSettings);
    expect(markup).not.toMatch(/Output length:|Model maximum:/);
  },
);
it.each([
  ["auto", ["auto", "off"], "true", false],
  ["auto", ["auto"], "true", true],
  ["off", ["auto", "off"], "false", false],
] as const)(
  "exposes an accessible thinking Switch for %s with modes %j",
  (thinkingMode, modes, checked, disabled) => {
    const value = controller({
      thinkingMode,
      availableThinkingModes: [...modes],
      maxTokens: thinkingMode === "off" ? "" : "8192",
    });
    const { container } = render(fields(value));
    const control = screen.getByRole("switch", { name: t.thinkingMode });
    expect(control.getAttribute("aria-checked")).toBe(checked);
    expect(
      (container.querySelector("input#model-thinking-mode") as HTMLInputElement)
        .disabled,
    ).toBe(disabled);
    expect(container.querySelector("#model-max-tokens")).not.toBeNull();
    fireEvent.click(control);
    if (disabled) expect(value.updateField).not.toHaveBeenCalled();
    else
      expect(value.updateField).toHaveBeenCalledWith(
        "thinkingMode",
        thinkingMode === "off" ? "auto" : "off",
      );
  },
);
it.each([
  [
    "thinkingMode",
    "This model cannot turn reasoning off.",
    "model-thinking-mode",
  ],
  [
    "maxTokens",
    "Must not exceed the model maximum (65536).",
    "model-max-tokens",
  ],
] as const)(
  "reveals the %s error with a stable accessible description",
  (field, error, id) => {
    const { container } = render(
      <form>
        {fields(
          controller(
            { maxTokens: "", thinkingMode: "off" },
            { errors: { [field]: error } },
          ),
        )}
      </form>,
    );
    expect(
      container
        .querySelector("#model-output-settings")
        ?.getAttribute("aria-invalid"),
    ).toBe("true");
    const control =
      field === "thinkingMode"
        ? screen.getByRole("switch")
        : container.querySelector(`#${id}`)!;
    expect(control.getAttribute("aria-invalid")).toBe("true");
    expect(control.getAttribute("aria-describedby")).toBe(`${id}-error`);
    expect(container.querySelector(`#${id}-error`)?.textContent).toBe(error);
    expect(
      container.querySelector(
        "#model-max-tokens-auto-hint, #model-max-tokens-maximum",
      ),
    ).toBeNull();
    expect(document.activeElement).toBe(control);
  },
);
it("keeps manual capabilities, context catalog and token inputs editable", () => {
  const value = controller({ providerKind: "local", supportsTools: false });
  const { container } = render(fields(value));
  fireEvent.click(screen.getByRole("checkbox", { name: t.toolUseCapability }));
  expect(value.updateField).toHaveBeenCalledWith("supportsTools", true);
  expect(
    screen.getByRole("button", { name: t.contextWindowCatalog }),
  ).not.toBeNull();
  fireEvent.change(container.querySelector("#model-context-window")!, {
    target: { value: "64000" },
  });
  expect(value.updateField).toHaveBeenCalledWith(
    "contextWindowTokens",
    "64000",
  );
  fireEvent.change(container.querySelector("#model-max-tokens")!, {
    target: { value: "4096" },
  });
  expect(value.updateField).toHaveBeenCalledWith("maxTokens", "4096");
});
it.each(["cloud", "local", "custom"] as const)(
  "only exposes typed API URLs for a loaded manual provider: %s",
  (providerKind) => {
    const value = controller(
      { providerKind },
      {
        errors: { provider: "Invalid provider" },
        selectedProvider: { ...cloud, kind: providerKind },
      },
    );
    const { container, rerender } = render(
      <ModelConfigProviderFields controller={value} messages={t} />,
    );
    expect(
      container.querySelector("#model-provider")?.getAttribute("aria-invalid"),
    ).toBe("true");
    expect(container.querySelector("#model-api-url") !== null).toBe(
      providerKind !== "cloud",
    );
    if (providerKind !== "cloud") {
      fireEvent.change(container.querySelector("#model-api-url")!, {
        target: { value: "http://manual.test/v1" },
      });
      expect(value.updateField).toHaveBeenCalledWith(
        "apiUrl",
        "http://manual.test/v1",
      );
    }
    rerender(
      <ModelConfigProviderFields
        controller={{ ...value, providersLoaded: false }}
        messages={t}
      />,
    );
    expect(container.querySelector("#model-api-url")).toBeNull();
  },
);
it("exposes invalid discovery state and an explicit refresh action", () => {
  const value = controller({}, { errors: { discovery: "Fetch models" } });
  const { container } = render(fields(value));
  expect(
    container.querySelector("#model-select")?.getAttribute("aria-invalid"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: t.refreshModels }));
  expect(value.refreshModels).toHaveBeenCalledOnce();
});
it.each([false, true])(
  "scrolls only the form viewport with reduced motion=%s",
  (reduced) => {
    vi.mocked(window.matchMedia).mockReturnValue({
      matches: reduced,
    } as MediaQueryList);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function (this: HTMLElement) {
        return {
          x: 0,
          y: 0,
          left: 0,
          right: 200,
          top: 0,
          bottom: this.id === "model-output-settings-content" ? 300 : 100,
          width: 200,
          height: this.id === "model-output-settings-content" ? 300 : 100,
          toJSON() {},
        };
      },
    );
    const scrollTo = vi.fn();
    const { container } = render(
      <div data-slot="field-group">
        {fields(controller({ maxTokens: "" }))}
      </div>,
    );
    const viewport = container.firstElementChild as HTMLElement;
    viewport.scrollTo = scrollTo;
    fireEvent.click(screen.getByRole("button", { name: t.advancedSettings }));
    expect(scrollTo).toHaveBeenCalledExactlyOnceWith({
      top: -12,
      behavior: reduced ? "auto" : "smooth",
    });
    expect(container.querySelector("#model-max-tokens")).not.toBeNull();
  },
);
it("focuses errors in visual order and uses enabled in-form fallbacks", () => {
  const { container } = render(
    <form>
      <input id="model-api-key" />
      <button id="model-select" disabled />
      <button id="model-discovery" />
      <input id="model-max-tokens" />
      <button id="model-output-settings" />
    </form>,
  );
  const form = container.querySelector("form")!;
  for (const [errors, id] of [
    [{ apiKey: "Required", model: "Required" }, "model-api-key"],
    [{ model: "Required", discovery: "Fetch models" }, "model-discovery"],
    [{ maxTokens: "Too large" }, "model-max-tokens"],
  ] as const) {
    expect(focusFirstModelConfigError(form, errors, "cloud")).toBe(true);
    expect(document.activeElement?.id).toBe(id);
  }
  form.querySelector("#model-max-tokens")!.remove();
  for (const errors of [
    { maxTokens: "Too large" },
    { thinkingMode: "Unsupported" },
  ]) {
    expect(focusFirstModelConfigError(form, errors, "cloud")).toBe(true);
    expect(document.activeElement?.id).toBe("model-output-settings");
  }
});
it("shows unsupported saved Agent models as unconfigured and lists only tool-capable choices", () => {
  const supported = {
    ...createDefaultModelConfig("en"),
    id: "supported",
    nickname: "Primary model",
    supportsTools: true,
  };
  const unsupported = {
    ...supported,
    id: "unsupported",
    nickname: "No-tools model",
    supportsTools: false,
  };
  const settings = {
    defaultModelConfigId: unsupported.id,
    responseLanguage: "follow",
    behaviorMode: "balanced",
    confirmationMode: "always",
  } as const;
  const onChange = vi.fn();
  const { rerender } = render(
    <Tabs value="agent">
      <AgentSettingsTab
        t={t}
        agentSettings={settings}
        modelConfigs={[unsupported, supported]}
        onAgentSettingsChange={onChange}
      />
    </Tabs>,
  );
  const select = screen.getByRole("combobox", { name: t.defaultAgentModel });
  expect(select.textContent).toBe(t.agentModelNotConfigured);
  fireEvent.keyDown(select, { key: "ArrowDown" });
  expect(screen.queryByRole("option", { name: "No-tools model" })).toBeNull();
  fireEvent.click(screen.getByRole("option", { name: "Primary model" }));
  expect(onChange).toHaveBeenCalledWith({
    ...settings,
    defaultModelConfigId: "supported",
  });
  rerender(
    <Tabs value="agent">
      <AgentSettingsTab
        t={t}
        agentSettings={settings}
        modelConfigs={[unsupported]}
        onAgentSettingsChange={onChange}
      />
    </Tabs>,
  );
  expect(
    (
      screen.getByRole("combobox", {
        name: t.defaultAgentModel,
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
