import type { AppMessages, Locale } from "@/i18n";
import {
  DEFAULT_CONTEXT_WINDOW_TOKENS,
  DEFAULT_MODEL_API_FAMILY,
  createDefaultModelConfig,
  normalizeMaxTokens,
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
      maxOutputTokens: config.maxTokens,
      supportsImage: config.supportsImage,
      supportsThinking: config.supportsThinking,
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
    supportsTools: source.supportsTools,
    supportsStreaming: source.supportsStreaming,
    thinkingEnabled: source.thinkingEnabled,
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
  if (draft.providerKind === "cloud") {
    if (!provider.defaultBaseUrl.trim() || !isValidHttpUrl(provider.defaultBaseUrl.trim())) {
      errors.discovery = messages.modelDiscoveryFailed;
    }
    if (!discoveredModels.some((model) => model.id === draft.model)) {
      errors.discovery = messages.modelDiscoveryRequired;
    }
    return errors;
  }
  if (!draft.apiUrl.trim()) {
    errors.apiUrl = messages.validationRequired;
  } else if (!isValidHttpUrl(draft.apiUrl.trim())) {
    errors.apiUrl = messages.validationApiUrl;
  }
  if (!/^\d+$/.test(draft.contextWindowTokens.trim()) || Number(draft.contextWindowTokens) <= 0) {
    errors.contextWindowTokens = messages.validationMaxTokens;
  }
  const maxTokens = draft.maxTokens.trim();
  if (maxTokens && (!/^\d+$/.test(maxTokens) || Number(maxTokens) <= 0)) {
    errors.maxTokens = messages.validationMaxTokens;
  }

  return errors;
}

export function applyDiscoveredModel(
  draft: ModelConfigDraft,
  model: DiscoveredModel,
) {
  return {
    ...draft,
    model: model.id,
    contextWindowTokens: String(model.contextWindowTokens),
    maxTokens:
      typeof model.maxOutputTokens === "number"
        ? String(model.maxOutputTokens)
        : "",
    supportsImage: model.supportsImage,
    supportsThinking: model.supportsThinking,
    supportsTools: model.supportsTools,
    supportsStreaming: model.supportsStreaming,
    thinkingEnabled: model.supportsThinking,
  };
}

export function changeDraftProvider(
  draft: ModelConfigDraft,
  provider: ModelProviderMeta,
) {
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
    supportsTools: provider.supportsTools,
    supportsStreaming: provider.supportsStreaming,
    thinkingEnabled: false,
  };
}

export function createSavedModelConfig(
  draft: ModelConfigDraft,
  provider: ModelProviderMeta,
  initialConfig?: ModelConfig,
) {
  const usesManualSettings = draft.providerKind !== "cloud";
  const supportsThinking = draft.supportsThinking;

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
    temperature: null,
    topP: null,
    maxTokens: usesManualSettings
      ? normalizeMaxTokens(Number(draft.maxTokens))
      : null,
    contextWindowTokens: Number(draft.contextWindowTokens),
    supportsImage: draft.supportsImage,
    supportsThinking,
    supportsTools: draft.supportsTools,
    supportsStreaming: draft.supportsStreaming,
    thinkingEnabled:
      supportsThinking && (usesManualSettings || draft.thinkingEnabled),
  } satisfies Omit<ModelConfig, "id"> & { id?: string };
}

export { isValidHttpUrl };
