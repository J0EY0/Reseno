// @vitest-environment node

import { expect, it } from "vitest";
import { defaultMessages as t } from "@/i18n";
import {
  applyDiscoveredModel,
  createModelConfigDraft,
  createSavedModelConfig,
  discoveredFromConfig,
  providerDisplayLabel,
  providerKindLabel,
  validateModelConfigDraft,
} from "@/components/models/model-config-draft";
import { classifyModelConfigSaveFailure } from "@/components/models/use-model-config-dialog";
import { normalizeModelConfigs } from "@/lib/model-config";
import type { ModelProviderMeta } from "@/lib/model-providers";
import type { DiscoveredModel } from "@/lib/model-config-api";
import type { ModelConfig } from "@/types/resume";

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
const local: ModelProviderMeta = {
  ...cloud,
  id: "ollama",
  kind: "local",
  label: "Ollama",
  defaultBaseUrl: "http://localhost:11434/v1",
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
const canonical: ModelConfig = {
  id: "model-canonical",
  provider: "openai",
  providerLabel: "OpenAI",
  iconProvider: "openai",
  providerKind: "cloud",
  apiFamily: "openai_responses",
  nickname: "Primary model",
  apiKeyPreview: "sk-••••",
  model: "gpt-test",
  apiUrl: "https://api.openai.com/v1",
  temperature: null,
  topP: null,
  maxTokens: 4096,
  contextWindowTokens: 128000,
  supportsImage: true,
  supportsThinking: true,
  thinkingMode: "auto",
  availableThinkingModes: ["auto", "off"],
  supportsTools: true,
  supportsStreaming: true,
};
const localDraft = {
  ...createModelConfigDraft("en"),
  provider: local.id,
  providerKind: local.kind,
  apiUrl: local.defaultBaseUrl,
  model: "qwen3:8b",
};
const cloudDraft = applyDiscoveredModel(
  {
    ...createModelConfigDraft("en"),
    provider: "openai",
    providerKind: "cloud",
    maxTokens: "8192",
  },
  model,
);

it("accepts only the canonical workspace model array", () => {
  expect(
    normalizeModelConfigs(
      {
        modelConfig: { provider: "openai", model: "legacy-model" },
      } as Parameters<typeof normalizeModelConfigs>[0],
      "en",
    ),
  ).toEqual([]);
  expect(normalizeModelConfigs({ modelConfigs: [canonical] }, "en")).toEqual([
    canonical,
  ]);
});
it("localizes provider labels and kinds and resolves the saved API URL by provider kind", () => {
  expect(providerDisplayLabel({ ...cloud, id: "custom-cloud" }, t)).toBe(
    t.customCloudApi,
  );
  expect(providerDisplayLabel(cloud, t)).toBe("OpenAI");
  expect(providerKindLabel(cloud, t)).toBe(t.cloudProvider);
  expect(providerKindLabel(local, t)).toBe(t.localProvider);
  expect(
    createSavedModelConfig(
      { ...cloudDraft, apiUrl: "https://wrong.test" },
      { ...cloud, defaultBaseUrl: " https://api.openai.com/v1 " },
    ).apiUrl,
  ).toBe("https://api.openai.com/v1");
  expect(
    createSavedModelConfig(
      { ...localDraft, apiUrl: " http://custom.local/v1 " },
      local,
    ).apiUrl,
  ).toBe("http://custom.local/v1");
});
it.each([
  [0, 1],
  [1.234, 0.8765],
  [2, 0.01],
])(
  "round-trips local sampling without losing precision: %s / %s",
  (temperature, topP) => {
    const input = {
      ...localDraft,
      temperature: String(temperature),
      topP: String(topP),
    };
    expect(validateModelConfigDraft(input, local, [], t)).toEqual({});
    const saved = createSavedModelConfig(input, local);
    const [normalized] = normalizeModelConfigs({ modelConfigs: [saved] }, "en");
    const restored = createModelConfigDraft("en", normalized);
    expect(saved).toMatchObject({ temperature, topP });
    expect(restored).toMatchObject({
      temperature: String(temperature),
      topP: String(topP),
    });
  },
);
it("saves blank sampling as Auto", () => {
  expect(
    createSavedModelConfig(
      { ...localDraft, temperature: " ", topP: "" },
      local,
    ),
  ).toMatchObject({ temperature: null, topP: null });
});
it.each([
  ...["-0.1", "2.01", "NaN", "Infinity", "1e999", "abc", "0x1"].map(
    (value) => ["temperature", value] as const,
  ),
  ...["0", "-0.1", "1.01", "NaN", "Infinity", "1e999", "abc", "0x1"].map(
    (value) => ["topP", value] as const,
  ),
])("rejects invalid %s: %s", (field, value) => {
  expect(
    validateModelConfigDraft({ ...localDraft, [field]: value }, local, [], t)[
      field
    ],
  ).toBe(field === "temperature" ? t.validationTemperature : t.validationTopP);
});
it.each(["cloud", "custom"] as const)(
  "does not submit sampling for %s providers",
  (providerKind) => {
    expect(
      createSavedModelConfig(
        { ...localDraft, providerKind, temperature: "1.234", topP: "0.8765" },
        cloud,
      ),
    ).toMatchObject({ temperature: null, topP: null });
  },
);
it("resets output overrides only when selecting a different model", () => {
  expect(cloudDraft.maxTokens).toBe("");
  expect(
    applyDiscoveredModel({ ...cloudDraft, maxTokens: "8192" }, model).maxTokens,
  ).toBe("8192");
  expect(discoveredFromConfig(canonical)[0]).toMatchObject({
    maxOutputTokens: null,
    availableThinkingModes: ["auto", "off"],
  });
});
it.each([
  [["auto"], "auto"],
  [["auto", "off"], "off"],
] as const)(
  "reconciles Off against authoritative modes %j",
  (modes, expected) => {
    expect(
      applyDiscoveredModel(
        { ...cloudDraft, thinkingMode: "off" },
        { ...model, availableThinkingModes: [...modes] },
      ).thinkingMode,
    ).toBe(expected);
  },
);
it("saves the thinking preference and explicit output override without server-derived capabilities", () => {
  const saved = createSavedModelConfig(
    { ...cloudDraft, maxTokens: "8192", thinkingMode: "off" },
    cloud,
  );
  expect(saved).toMatchObject({
    supportsThinking: true,
    thinkingMode: "off",
    maxTokens: 8192,
  });
  expect(saved).not.toHaveProperty("availableThinkingModes");
  expect(saved).not.toHaveProperty("thinkingEnabled");
  expect(
    createSavedModelConfig(
      { ...createModelConfigDraft("en"), providerKind: "cloud" },
      cloud,
    ).maxTokens,
  ).toBeNull();
});
it.each([
  ["0", 65536, t.validationMaxTokens],
  ["65537", 65536, t.validationMaxTokensExceeded.replace("{count}", "65536")],
  ["131072", null, undefined],
  ["9007199254740992", null, t.validationMaxTokens],
] as const)(
  "validates output %s against the known ceiling %s",
  (maxTokens, maxOutputTokens, expected) => {
    expect(
      validateModelConfigDraft(
        { ...cloudDraft, maxTokens },
        cloud,
        [{ ...model, maxOutputTokens }],
        t,
      ).maxTokens,
    ).toBe(expected);
  },
);
it.each([
  [
    "MODEL_CONFIG_MAX_TOKENS_EXCEEDS_LIMIT",
    "The output limit exceeds this model's maximum.",
    "invalid",
    "maxTokens",
  ],
  [
    "MODEL_CONFIG_MAX_TOKENS_INVALID",
    "Enter an integer greater than 0.",
    "invalid",
    "maxTokens",
  ],
  [
    "MODEL_CONFIG_THINKING_MODE_UNSUPPORTED",
    "This model cannot turn reasoning off. Select Auto instead.",
    "invalid",
    "thinkingMode",
  ],
  [undefined, "Save failed", "failed", "discovery"],
])(
  "classifies save error %s without hiding field feedback",
  (apiCode, message, status, field) => {
    expect(
      classifyModelConfigSaveFailure(
        Object.assign(new Error(message), { apiCode }),
        t,
      ),
    ).toEqual({ status, errors: { [field!]: message } });
  },
);
