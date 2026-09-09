import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages, Locale } from "@/i18n";
import { isApiErrorCode } from "@/lib/api-client";
import { DEFAULT_CONTEXT_WINDOW_TOKENS } from "@/lib/model-config";
import {
  discoverModels,
  getModelProviders,
  saveModelConfig,
  type DiscoveredModel,
} from "@/lib/model-config-api";
import type { ModelProviderMeta } from "@/lib/model-providers";
import type { ModelConfig } from "@/types/resume";

import {
  applyDiscoveredModel,
  changeDraftProvider,
  createDialogModelConfigDraft,
  createModelConfigDraft,
  createSavedModelConfig,
  discoveredFromConfig,
  isValidHttpUrl,
  providerById,
  validateModelConfigDraft,
  type ModelConfigDraft,
  type ModelConfigErrors,
} from "./model-config-draft";

interface UseModelConfigDialogOptions {
  initialConfig?: ModelConfig;
  locale: Locale;
  messages: AppMessages;
  mode: "create" | "edit";
  onSaved: (config: ModelConfig) => void;
}

export function classifyModelConfigSaveFailure(
  error: unknown,
  messages: Pick<AppMessages, "validationRequired">,
) {
  const message =
    error instanceof Error ? error.message : messages.validationRequired;
  const isOutputLimitError =
    isApiErrorCode(error, "MODEL_CONFIG_MAX_TOKENS_INVALID") ||
    isApiErrorCode(error, "MODEL_CONFIG_MAX_TOKENS_EXCEEDS_LIMIT");

  if (isOutputLimitError) {
    return {
      status: "invalid",
      errors: { maxTokens: message },
    } as const;
  }

  const isThinkingModeError =
    isApiErrorCode(error, "MODEL_CONFIG_THINKING_MODE_INVALID") ||
    isApiErrorCode(error, "MODEL_CONFIG_THINKING_MODE_UNSUPPORTED");

  if (isThinkingModeError) {
    return {
      status: "invalid",
      errors: { thinkingMode: message },
    } as const;
  }

  return {
    status: "failed",
    errors: { discovery: message },
  } as const;
}

export function useModelConfigDialog({
  initialConfig,
  locale,
  messages,
  mode,
  onSaved,
}: UseModelConfigDialogOptions) {
  const [providers, setProviders] = useState<ModelProviderMeta[]>([]);
  const [providersLoaded, setProvidersLoaded] = useState(false);
  const [draft, setDraft] = useState(() =>
    createModelConfigDraft(locale, initialConfig),
  );
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>(
    () => discoveredFromConfig(initialConfig),
  );
  const [modelOptionsLoaded, setModelOptionsLoaded] = useState(false);
  const [errors, setErrors] = useState<ModelConfigErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const discoveryRequestIdRef = useRef(0);
  const selectedProvider = useMemo(
    () => providerById(providers, draft.provider),
    [draft.provider, providers],
  );
  const modelDiscoveryApiUrl =
    draft.providerKind === "cloud"
      ? (selectedProvider?.defaultBaseUrl.trim() ?? "")
      : draft.apiUrl.trim();
  const canDiscoverModels =
    draft.providerKind === "cloud" &&
    Boolean(selectedProvider?.supportsModelDiscovery);
  const modelOptionsLoading =
    !providersLoaded || (canDiscoverModels && !modelOptionsLoaded);

  const applyDiscoveredModels = useCallback((models: DiscoveredModel[]) => {
    setDiscoveredModels(models);
    setDraft((current) => {
      const selectedModel =
        models.find((model) => model.id === current.model) ??
        (models.length === 1 ? models[0] : null);

      if (selectedModel) {
        return applyDiscoveredModel(current, selectedModel);
      }
      if (models.length === 0 || current.providerKind !== "cloud") {
        return current;
      }

      return {
        ...current,
        model: "",
        maxTokens: "",
        contextWindowTokens: String(DEFAULT_CONTEXT_WINDOW_TOKENS),
        supportsImage: false,
        supportsThinking: false,
        thinkingMode: "auto",
        availableThinkingModes: ["auto"],
        supportsTools: true,
        supportsStreaming: true,
      };
    });
    setErrors((current) => {
      const next = { ...current };
      delete next.discovery;
      if (models.length === 1) {
        delete next.model;
      }
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;

    void getModelProviders()
      .then((response) => {
        if (!cancelled) {
          const nextDraft = createDialogModelConfigDraft(
            locale,
            initialConfig,
            response.providers,
          );
          const nextProvider = providerById(
            response.providers,
            nextDraft.provider,
          );

          setProviders(response.providers);
          setDraft(nextDraft);
          setModelOptionsLoaded(
            !(
              nextDraft.providerKind === "cloud" &&
              nextProvider?.supportsModelDiscovery
            ),
          );
          setProvidersLoaded(true);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Failed to load model providers.", error);
          setModelOptionsLoaded(true);
          setProvidersLoaded(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [initialConfig, locale]);

  useEffect(() => {
    if (!canDiscoverModels || !modelDiscoveryApiUrl) {
      setModelOptionsLoaded(true);
      return;
    }

    let cancelled = false;
    setModelOptionsLoaded(false);
    void discoverModels({
      provider: draft.provider,
      apiFamily: draft.apiFamily,
      apiUrl: modelDiscoveryApiUrl,
      configId: initialConfig?.id,
    })
      .then((response) => {
        if (!cancelled) {
          applyDiscoveredModels(response.models);
          setModelOptionsLoaded(true);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Failed to load cached models.", error);
          setModelOptionsLoaded(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    applyDiscoveredModels,
    canDiscoverModels,
    draft.apiFamily,
    draft.provider,
    initialConfig?.id,
    modelDiscoveryApiUrl,
  ]);

  const updateField = useCallback(
    <Key extends keyof ModelConfigDraft>(
      field: Key,
      value: ModelConfigDraft[Key],
    ) => {
      setDraft((current) => ({ ...current, [field]: value }));
      setErrors((current) => {
        if (!current[field]) {
          return current;
        }
        const next = { ...current };
        delete next[field];
        return next;
      });
    },
    [],
  );

  const selectProvider = useCallback(
    (providerId: string) => {
      const provider = providerById(providers, providerId);

      if (!provider) {
        return;
      }

      discoveryRequestIdRef.current += 1;
      setDiscovering(false);
      setDraft((current) => changeDraftProvider(current, provider));
      setDiscoveredModels([]);
      setModelOptionsLoaded(
        provider.kind !== "cloud" || !provider.supportsModelDiscovery,
      );
      setErrors({});
    },
    [providers],
  );

  const selectModel = useCallback(
    (modelId: string) => {
      const model = discoveredModels.find((item) => item.id === modelId);

      if (!model) {
        return;
      }

      setDraft((current) => applyDiscoveredModel(current, model));
      setErrors((current) => {
        const next = { ...current };
        delete next.model;
        delete next.discovery;
        return next;
      });
    },
    [discoveredModels],
  );

  const refreshModels = useCallback(async () => {
    const validationErrors: ModelConfigErrors = {};

    if (!selectedProvider) {
      validationErrors.provider = messages.validationRequired;
    } else if (
      selectedProvider.authRequired &&
      !draft.apiKey.trim() &&
      !draft.apiKeyPreview.trim()
    ) {
      validationErrors.apiKey = messages.validationRequired;
    }
    if (!selectedProvider?.supportsModelDiscovery) {
      validationErrors.discovery = messages.modelDiscoveryFailed;
    }
    if (!modelDiscoveryApiUrl || !isValidHttpUrl(modelDiscoveryApiUrl)) {
      if (draft.providerKind === "cloud") {
        validationErrors.discovery = messages.modelDiscoveryFailed;
      } else {
        validationErrors.apiUrl = modelDiscoveryApiUrl
          ? messages.validationApiUrl
          : messages.validationRequired;
      }
    }
    if (Object.keys(validationErrors).length > 0) {
      setErrors((current) => ({ ...current, ...validationErrors }));
      return;
    }

    const requestId = ++discoveryRequestIdRef.current;
    setDiscovering(true);
    setErrors((current) => {
      const next = { ...current };
      delete next.discovery;
      return next;
    });

    try {
      const response = await discoverModels({
        provider: draft.provider,
        apiFamily: draft.apiFamily,
        apiUrl: modelDiscoveryApiUrl,
        apiKey: draft.apiKey.trim() || undefined,
        configId: initialConfig?.id,
        refresh: true,
      });
      if (requestId !== discoveryRequestIdRef.current) {
        return;
      }
      applyDiscoveredModels(response.models);
    } catch (error) {
      if (requestId !== discoveryRequestIdRef.current) {
        return;
      }
      if (discoveredModels.length === 0) {
        setDraft((current) => ({
          ...current,
          model: "",
          supportsImage: false,
          supportsThinking: false,
          thinkingMode: "auto",
          availableThinkingModes: ["auto"],
          supportsTools: selectedProvider?.supportsTools ?? true,
          supportsStreaming: selectedProvider?.supportsStreaming ?? true,
        }));
      }
      setErrors((current) => ({
        ...current,
        discovery:
          error instanceof Error
            ? error.message
            : messages.modelDiscoveryFailed,
      }));
    } finally {
      if (requestId === discoveryRequestIdRef.current) {
        setDiscovering(false);
      }
    }
  }, [
    applyDiscoveredModels,
    discoveredModels.length,
    draft,
    initialConfig?.id,
    messages,
    modelDiscoveryApiUrl,
    selectedProvider,
  ]);

  const submit = useCallback(async () => {
    const nextErrors = validateModelConfigDraft(
      draft,
      selectedProvider,
      discoveredModels,
      messages,
    );

    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return { status: "invalid", errors: nextErrors } as const;
    }
    if (!selectedProvider) {
      return { status: "failed" } as const;
    }

    setSubmitting(true);
    try {
      const savedConfig = await saveModelConfig(
        createSavedModelConfig(draft, selectedProvider, initialConfig),
        draft.apiKey.trim() || undefined,
      );
      onSaved(savedConfig);
      toast.success(
        mode === "create"
          ? messages.modelConfigCreated
          : messages.modelConfigUpdated,
        { closeButton: true },
      );
      return { status: "saved" } as const;
    } catch (error) {
      const result = classifyModelConfigSaveFailure(error, messages);
      setErrors((current) => ({ ...current, ...result.errors }));
      return result;
    } finally {
      setSubmitting(false);
    }
  }, [
    discoveredModels,
    draft,
    initialConfig,
    messages,
    mode,
    onSaved,
    selectedProvider,
  ]);

  return {
    canDiscoverModels,
    discovering,
    discoveredModels,
    draft,
    errors,
    modelOptionsLoading,
    providers,
    providersLoaded,
    refreshModels,
    selectModel,
    selectProvider,
    selectedProvider,
    submit,
    submitting,
    updateField,
  };
}

export type ModelConfigDialogController = ReturnType<
  typeof useModelConfigDialog
>;
