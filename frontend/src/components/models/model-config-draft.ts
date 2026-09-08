import type { AppMessages, Locale } from "@/i18n";
import {
  DEFAULT_CONTEXT_WINDOW_TOKENS,
  DEFAULT_MODEL_API_FAMILY,
  createDefaultModelConfig,
  normalizeAvailableThinkingModes,
  normalizeMaxTokens,
  resolveThinkingMode,
} from "@/lib/model-config";
import type { DiscoveredModel } from "@/lib/model-config-api";
import type { ModelProviderMeta } from "@/lib/model-providers";
import type { ModelConfig } from "@/types/resume";

export type ModelConfigDraft = Omit<
  ModelConfig,
  | "id"
  | "providerLabel"
  | "iconProvider"
  | "temperature"
  | "topP"
  | "maxTokens"
  | "contextWindowTokens"
> & {
  apiKey: string;
  temperature: string;
  topP: string;
  maxTokens: string;
  contextWindowTokens: string;
};

export type ModelConfigErrors = Partial<
  Record<keyof ModelConfigDraft | "discovery", string>
>;

export function providerById(
  providers: ModelProviderMeta[],
  providerId: string,
) {
  return providers.find((provider) => provider.id === providerId) ?? null;
}

export function providerDisplayLabel(
  provider: ModelProviderMeta,
  messages: AppMessages,
) {
  return provider.id === "custom-cloud"
    ? messages.customCloudApi
    : provider.label;
}

export function providerKindLabel(
  provider: ModelProviderMeta,
  messages: AppMessages,
) {
  return provider.kind === "local"
    ? messages.localProvider
    : messages.cloudProvider;
}

export function discoveredFromConfig(config?: ModelConfig): DiscoveredModel[] {
  if (!config || config.providerKind !== "cloud") {
    return [];
  }

  return [
    {
      id: config.model,
      label: config.model,
      contextWindowTokens: config.contextWindowTokens,
      // Saved configs only contain the per-request override. Treat the model
      // capability as unknown until discovery returns authoritative metadata.
      maxOutputTokens: null,
      supportsImage: config.supportsImage,
      supportsThinking: config.supportsThinking,
      availableThinkingModes: config.availableThinkingModes,
      supportsTools: config.supportsTools,
      supportsStreaming: config.supportsStreaming,
      metadataSource: "saved",
    },
  ];
}

export function createModelConfigDraft(
  locale: Locale,
  config?: ModelConfig,
): ModelConfigDraft {
  const source = config ?? createDefaultModelConfig(locale);

  return {
    provider: source.provider,
    providerKind: source.providerKind,
    apiFamily: source.apiFamily,
    nickname: source.nickname,
    apiKeyPreview: source.apiKeyPreview,
    apiKey: "",
    model: source.model,
    apiUrl: source.apiUrl,
    temperature:
      typeof source.temperature === "number" ? String(source.temperature) : "",
    topP: typeof source.topP === "number" ? String(source.topP) : "",
    maxTokens:
      typeof source.maxTokens === "number" ? String(source.maxTokens) : "",
    contextWindowTokens: String(
      source.contextWindowTokens || DEFAULT_CONTEXT_WINDOW_TOKENS,
    ),
    supportsImage: source.supportsImage,
    supportsThinking: source.supportsThinking,
    thinkingMode: source.thinkingMode,
    availableThinkingModes: source.availableThinkingModes,
    supportsTools: source.supportsTools,
    supportsStreaming: source.supportsStreaming,
  };
}

export function createDialogModelConfigDraft(
  locale: Locale,
  initialConfig: ModelConfig | undefined,
  providers: ModelProviderMeta[],
) {
  const draft = createModelConfigDraft(locale, initialConfig);
  const provider =
    providerById(providers, draft.provider) ??
    (initialConfig ? null : providers[0]);

  if (!provider) {
    return draft;
  }

  if (initialConfig) {
    return {
      ...draft,
      provider: provider.id,
      providerKind: provider.kind,
      apiFamily: provider.apiFamily ?? draft.apiFamily,
      apiUrl:
        provider.kind === "cloud" ? provider.defaultBaseUrl : draft.apiUrl,
    };
  }

  return {
    ...draft,
    provider: provider.id,
    providerKind: provider.kind,
    apiFamily: provider.apiFamily ?? DEFAULT_MODEL_API_FAMILY,
    apiUrl: provider.defaultBaseUrl,
    supportsTools: provider.supportsTools,
    supportsStreaming: provider.supportsStreaming,
  };
}

function isValidHttpUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function validateModelConfigDraft(
  draft: ModelConfigDraft,
  provider: ModelProviderMeta | null,
  discoveredModels: DiscoveredModel[],
  messages: AppMessages,
): ModelConfigErrors {
  const errors: ModelConfigErrors = {};

  if (!provider) {
    errors.provider = messages.validationRequired;
    return errors;
  }
  if (!draft.provider.trim()) {
    errors.provider = messages.validationRequired;
  }
  if (!draft.apiFamily) {
    errors.apiFamily = messages.validationRequired;
  }
  if (!draft.model.trim()) {
    errors.model = messages.validationRequired;
  }
  if (provider.authRequired && !draft.apiKey.trim() && !draft.apiKeyPreview.trim()) {
    errors.apiKey = messages.validationRequired;
  }
  const maxTokens = draft.maxTokens.trim();
  const parsedMaxTokens = Number(maxTokens);
  if (
    maxTokens &&
    (!/^\d+$/.test(maxTokens) ||
      !Number.isSafeInteger(parsedMaxTokens) ||
      parsedMaxTokens <= 0)
  ) {
    errors.maxTokens = messages.validationMaxTokens;
  }
  const selectedModel = discoveredModels.find(
    (model) => model.id === draft.model,
  );
  const modelMaxOutputTokens = selectedModel?.maxOutputTokens;
  if (
    maxTokens &&
    !errors.maxTokens &&
    typeof modelMaxOutputTokens === "number" &&
    parsedMaxTokens > modelMaxOutputTokens
  ) {
    errors.maxTokens = messages.validationMaxTokensExceeded.replace(
      "{count}",
      String(modelMaxOutputTokens),
    );
  }
  if (draft.providerKind === "cloud") {
    if (!provider.defaultBaseUrl.trim() || !isValidHttpUrl(provider.defaultBaseUrl.trim())) {
      errors.discovery = messages.modelDiscoveryFailed;
    }
    if (!discoveredModels.some((model) => model.id === draft.model)) {
      errors.discovery = messages.modelDiscoveryRequired;
    }
    return errors;
  }
  if (draft.providerKind === "local") {
    for (const field of ["temperature", "topP"] as const) {
      const value = draft[field].trim();
      const parsed = Number(value);
      if (
        value &&
        (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value) ||
          !Number.isFinite(parsed) ||
          (field === "temperature" ? parsed < 0 || parsed > 2 : parsed <= 0 || parsed > 1))
      ) {
        errors[field] = field === "temperature"
          ? messages.validationTemperature
          : messages.validationTopP;
      }
    }
  }
  if (!draft.apiUrl.trim()) {
    errors.apiUrl = messages.validationRequired;
  } else if (!isValidHttpUrl(draft.apiUrl.trim())) {
    errors.apiUrl = messages.validationApiUrl;
  }
  if (!/^\d+$/.test(draft.contextWindowTokens.trim()) || Number(draft.contextWindowTokens) <= 0) {
    errors.contextWindowTokens = messages.validationMaxTokens;
  }
  return errors;
}

export function applyDiscoveredModel(
  draft: ModelConfigDraft,
  model: DiscoveredModel,
): ModelConfigDraft {
  const modelChanged = draft.model !== model.id;
  const availableThinkingModes = normalizeAvailableThinkingModes(
    model.availableThinkingModes,
  );
  const thinkingMode = resolveThinkingMode(
    draft.thinkingMode,
    availableThinkingModes,
  );

  return {
    ...draft,
    model: model.id,
    contextWindowTokens: String(model.contextWindowTokens),
    // maxOutputTokens is a discovered capability ceiling; maxTokens is an
    // optional user override. Copying one into the other would turn Auto into
    // a persisted hard limit and make later capability refreshes ambiguous.
    maxTokens: modelChanged ? "" : draft.maxTokens,
    supportsImage: model.supportsImage,
    supportsThinking: model.supportsThinking,
    // Discovery is authoritative for model capabilities. Preserve an explicit
    // Off preference only when the newly selected model also supports it;
    // otherwise return to provider-managed Auto before the form can be saved.
    thinkingMode,
    availableThinkingModes,
    supportsTools: model.supportsTools,
    supportsStreaming: model.supportsStreaming,
  };
}

export function changeDraftProvider(
  draft: ModelConfigDraft,
  provider: ModelProviderMeta,
): ModelConfigDraft {
  return {
    ...draft,
    provider: provider.id,
    providerKind: provider.kind,
    apiFamily: provider.apiFamily ?? DEFAULT_MODEL_API_FAMILY,
    apiUrl: provider.defaultBaseUrl,
    apiKey: "",
    apiKeyPreview: "",
    model: "",
    temperature: "",
    topP: "",
    maxTokens: "",
    contextWindowTokens: String(DEFAULT_CONTEXT_WINDOW_TOKENS),
    supportsImage: false,
    supportsThinking: false,
    thinkingMode: "auto",
    availableThinkingModes: ["auto"],
    supportsTools: provider.supportsTools,
    supportsStreaming: provider.supportsStreaming,
  };
}

export function createSavedModelConfig(
  draft: ModelConfigDraft,
  provider: ModelProviderMeta,
  initialConfig?: ModelConfig,
) {
  return {
    ...(initialConfig?.id ? { id: initialConfig.id } : {}),
    provider: draft.provider,
    providerLabel: provider.label,
    iconProvider: provider.iconProvider,
    providerKind: draft.providerKind,
    apiFamily: draft.apiFamily,
    nickname: draft.nickname.trim(),
    apiKeyPreview: draft.apiKeyPreview.trim(),
    model: draft.model.trim(),
    apiUrl:
      draft.providerKind === "cloud"
        ? provider.defaultBaseUrl.trim()
        : draft.apiUrl.trim(),
    temperature:
      draft.providerKind === "local" && draft.temperature.trim()
        ? Number(draft.temperature)
        : null,
    topP:
      draft.providerKind === "local" && draft.topP.trim()
        ? Number(draft.topP)
        : null,
    // An empty draft value is Auto (null); a number is an intentional request
    // override for every provider kind, including official cloud providers.
    maxTokens: normalizeMaxTokens(Number(draft.maxTokens)),
    contextWindowTokens: Number(draft.contextWindowTokens),
    supportsImage: draft.supportsImage,
    supportsThinking: draft.supportsThinking,
    thinkingMode: resolveThinkingMode(
      draft.thinkingMode,
      draft.availableThinkingModes,
    ),
    supportsTools: draft.supportsTools,
    supportsStreaming: draft.supportsStreaming,
  } satisfies Omit<ModelConfig, "id" | "availableThinkingModes"> & {
    id?: string;
  };
}

export { isValidHttpUrl };
