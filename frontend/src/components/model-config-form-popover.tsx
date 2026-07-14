import { ExternalLink, Plus } from "lucide-react";
import {
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import type { AppMessages, Locale } from "@/i18n";
import {
  DEFAULT_CONTEXT_WINDOW_TOKENS,
  DEFAULT_MODEL_API_FAMILY,
  createDefaultModelConfig,
  normalizeMaxTokens,
} from "@/lib/model-config";
import {
  discoverModels,
  getModelProviders,
  saveModelConfig,
  type DiscoveredModel,
} from "@/lib/model-config-api";
import type { ModelProviderMeta } from "@/lib/model-providers";
import type { ModelConfig } from "@/types/resume";

import { ModelProviderIcon } from "@/components/model-provider-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

type ModelConfigDraft = Omit<
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

type ModelConfigErrors = Partial<Record<keyof ModelConfigDraft | "discovery", string>>;

function FormFieldLabel({
  label,
  required = false,
  htmlFor,
}: {
  label: string;
  required?: boolean;
  htmlFor?: string;
}) {
  return (
    <FieldLabel htmlFor={htmlFor}>
      <span>{label}</span>
      {required ? <span className="text-destructive">*</span> : null}
    </FieldLabel>
  );
}

function ProviderKindBadge({ children }: { children: ReactNode }) {
  return (
    <Badge
      variant="outline"
      className="h-4 px-1 py-0 text-[9px] font-normal text-muted-foreground"
    >
      {children}
    </Badge>
  );
}

function isValidHttpUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function isValidMaxTokens(value: string) {
  const trimmed = value.trim();
  return !trimmed || (/^\d+$/.test(trimmed) && Number(trimmed) > 0);
}

function isValidContextWindow(value: string) {
  return /^\d+$/.test(value.trim()) && Number(value) > 0;
}

function providerById(providers: ModelProviderMeta[], providerId: string) {
  return providers.find((provider) => provider.id === providerId) ?? null;
}

function providerDisplayLabel(provider: ModelProviderMeta, t: AppMessages) {
  return provider.id === "custom-cloud" ? t.customCloudApi : provider.label;
}

function providerKindLabel(provider: ModelProviderMeta, t: AppMessages) {
  return provider.kind === "local" ? t.localProvider : t.cloudProvider;
}

function discoveredFromConfig(config?: ModelConfig): DiscoveredModel[] {
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

function toDraft(locale: Locale, config?: ModelConfig): ModelConfigDraft {
  const fallback = createDefaultModelConfig(locale);
  const source = config ?? fallback;

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

function validateDraft(
  draft: ModelConfigDraft,
  provider: ModelProviderMeta | null,
  discoveredModels: DiscoveredModel[],
  t: AppMessages,
): ModelConfigErrors {
  const errors: ModelConfigErrors = {};

  if (!provider) {
    errors.provider = t.validationRequired;
    return errors;
  }
  if (!draft.provider.trim()) {
    errors.provider = t.validationRequired;
  }
  if (!draft.apiFamily) {
    errors.apiFamily = t.validationRequired;
  }
  if (!draft.model.trim()) {
    errors.model = t.validationRequired;
  }
  if (provider.authRequired && !draft.apiKey.trim() && !draft.apiKeyPreview.trim()) {
    errors.apiKey = t.validationRequired;
  }
  if (draft.providerKind === "cloud") {
    if (
      !provider.defaultBaseUrl.trim() ||
      !isValidHttpUrl(provider.defaultBaseUrl.trim())
    ) {
      errors.discovery = t.modelDiscoveryFailed;
    }
    if (!discoveredModels.some((model) => model.id === draft.model)) {
      errors.discovery = t.modelDiscoveryRequired;
    }
    return errors;
  }
  if (!draft.apiUrl.trim()) {
    errors.apiUrl = t.validationRequired;
  } else if (!isValidHttpUrl(draft.apiUrl.trim())) {
    errors.apiUrl = t.validationApiUrl;
  }
  if (!isValidContextWindow(draft.contextWindowTokens)) {
    errors.contextWindowTokens = t.validationMaxTokens;
  }
  if (!isValidMaxTokens(draft.maxTokens)) {
    errors.maxTokens = t.validationMaxTokens;
  }

  return errors;
}

export function ModelConfigFormPopover({
  t,
  locale,
  mode,
  initialConfig,
  trigger,
  onSubmit,
}: {
  t: AppMessages;
  locale: Locale;
  mode: "create" | "edit";
  initialConfig?: ModelConfig;
  trigger?: ReactNode;
  onSubmit: (value: ModelConfig) => void;
}) {
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState<ModelProviderMeta[]>([]);
  const [providersLoaded, setProvidersLoaded] = useState(false);
  const [draft, setDraft] = useState<ModelConfigDraft>(() =>
    toDraft(locale, initialConfig),
  );
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>(
    () => discoveredFromConfig(initialConfig),
  );
  const [errors, setErrors] = useState<ModelConfigErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [discovering, setDiscovering] = useState(false);

  const selectedProvider = useMemo(
    () => providerById(providers, draft.provider),
    [draft.provider, providers],
  );
  const cloudProviders = providers.filter((provider) => provider.kind === "cloud");
  const cloudApiUrl = selectedProvider?.defaultBaseUrl.trim() ?? "";
  const canDiscoverModels =
    draft.providerKind === "cloud" && Boolean(selectedProvider?.supportsModelDiscovery);
  const modelDiscoveryApiUrl =
    draft.providerKind === "cloud" ? cloudApiUrl : draft.apiUrl.trim();
  const usesDiscoveredModelSelect =
    Boolean(selectedProvider) && draft.providerKind === "cloud";
  const usesManualModelSettings =
    Boolean(selectedProvider) && !usesDiscoveredModelSelect;
  const modelSelectPlaceholder = draft.model
    ? draft.model
    : discoveredModels.length > 0
      ? t.modelDiscoverySelectFetched
      : t.modelDiscoveryRequired;
  const discoveryButtonLabel = discovering
    ? t.fetchingModels
    : discoveredModels.length > 0
      ? t.refreshModels
      : t.fetchModels;

  const applyDiscoveredModels = useCallback(
    (nextModels: DiscoveredModel[]) => {
      setDiscoveredModels(nextModels);
      setDraft((current) => {
        const selectedModel =
          nextModels.find((item) => item.id === current.model) ??
          (nextModels.length === 1 ? nextModels[0] : null);

        if (!selectedModel) {
          if (nextModels.length > 0 && current.providerKind === "cloud") {
            return {
              ...current,
              model: "",
              maxTokens: "",
              contextWindowTokens: String(DEFAULT_CONTEXT_WINDOW_TOKENS),
              supportsImage: false,
              supportsThinking: false,
              supportsTools: true,
              supportsStreaming: true,
              thinkingEnabled: false,
            };
          }

          return current;
        }

        return {
          ...current,
          model: selectedModel.id,
          contextWindowTokens: String(selectedModel.contextWindowTokens),
          maxTokens:
            typeof selectedModel.maxOutputTokens === "number"
              ? String(selectedModel.maxOutputTokens)
              : "",
          supportsImage: selectedModel.supportsImage,
          supportsThinking: selectedModel.supportsThinking,
          supportsTools: selectedModel.supportsTools,
          supportsStreaming: selectedModel.supportsStreaming,
          thinkingEnabled: selectedModel.supportsThinking,
        };
      });
      setErrors((current) => {
        const next = { ...current };
        delete next.discovery;
        if (nextModels.length === 1) {
          delete next.model;
        }
        return next;
      });
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;

    void getModelProviders()
      .then((response) => {
        if (!cancelled) {
          setProviders(response.providers);
          setProvidersLoaded(true);
        }
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }

        console.error("Failed to load model providers.", error);
        setProvidersLoaded(true);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!open || !canDiscoverModels || !modelDiscoveryApiUrl) {
      return;
    }

    let cancelled = false;
    void discoverModels({
      provider: draft.provider,
      apiFamily: draft.apiFamily,
      apiUrl: modelDiscoveryApiUrl,
      configId: initialConfig?.id,
    })
      .then((response) => {
        if (!cancelled) {
          applyDiscoveredModels(response.models);
        }
      })
      .catch((error) => {
        console.error("Failed to load cached models.", error);
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
    open,
  ]);

  function updateField<Key extends keyof ModelConfigDraft>(
    field: Key,
    value: ModelConfigDraft[Key],
  ) {
    setDraft((current) => ({
      ...current,
      [field]: value,
    }));
    setErrors((current) => {
      if (!current[field]) {
        return current;
      }

      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  function handleProviderChange(nextProvider: string) {
    const nextProviderMeta = providerById(providers, nextProvider);
    if (!nextProviderMeta) {
      return;
    }

    const nextApiFamily = nextProviderMeta.apiFamily ?? DEFAULT_MODEL_API_FAMILY;

    setDraft((current) => ({
      ...current,
      provider: nextProviderMeta.id,
      providerKind: nextProviderMeta.kind,
      apiFamily: nextApiFamily,
      apiUrl: nextProviderMeta.defaultBaseUrl,
      apiKey: "",
      apiKeyPreview: "",
      model: "",
      temperature: "",
      topP: "",
      maxTokens: "",
      contextWindowTokens: String(DEFAULT_CONTEXT_WINDOW_TOKENS),
      supportsImage: false,
      supportsThinking: false,
      supportsTools: nextProviderMeta.supportsTools,
      supportsStreaming: nextProviderMeta.supportsStreaming,
      thinkingEnabled: false,
    }));
    setDiscoveredModels([]);
    setErrors({});
  }

  function handleApiKeyChange(value: string) {
    updateField("apiKey", value);
  }

  function handleApiUrlChange(value: string) {
    updateField("apiUrl", value);
  }

  function handleModelSelect(modelId: string) {
    const model = discoveredModels.find((item) => item.id === modelId);
    if (!model) {
      return;
    }

    setDraft((current) => ({
      ...current,
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
    }));
    setErrors((current) => {
      const next = { ...current };
      delete next.model;
      delete next.discovery;
      return next;
    });
  }

  async function handleDiscoverModels() {
    const validationErrors: ModelConfigErrors = {};
    if (!selectedProvider) {
      validationErrors.provider = t.validationRequired;
    } else if (
      selectedProvider.authRequired &&
      !draft.apiKey.trim() &&
      !draft.apiKeyPreview.trim()
    ) {
      validationErrors.apiKey = t.validationRequired;
    }
    if (!selectedProvider?.supportsModelDiscovery) {
      validationErrors.discovery = t.modelDiscoveryFailed;
    }
    if (!modelDiscoveryApiUrl || !isValidHttpUrl(modelDiscoveryApiUrl)) {
      if (draft.providerKind === "cloud") {
        validationErrors.discovery = t.modelDiscoveryFailed;
      } else {
        validationErrors.apiUrl = modelDiscoveryApiUrl
          ? t.validationApiUrl
          : t.validationRequired;
      }
    }
    if (Object.keys(validationErrors).length > 0) {
      setErrors((current) => ({ ...current, ...validationErrors }));
      return;
    }

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
      applyDiscoveredModels(response.models);
    } catch (error) {
      if (discoveredModels.length === 0) {
        setDiscoveredModels([]);
        setDraft((current) => ({
          ...current,
          model: "",
          supportsImage: false,
          supportsThinking: false,
          supportsTools: selectedProvider?.supportsTools ?? true,
          supportsStreaming: selectedProvider?.supportsStreaming ?? true,
          thinkingEnabled: false,
        }));
      }
      setErrors((current) => ({
        ...current,
        discovery:
          error instanceof Error ? error.message : t.modelDiscoveryFailed,
      }));
    } finally {
      setDiscovering(false);
    }
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      if (!providersLoaded) {
        return;
      }

      const baseDraft = toDraft(locale, initialConfig);
      const nextProvider =
        providerById(providers, baseDraft.provider) ??
        (initialConfig ? null : providers[0]);
      let nextDraft = baseDraft;

      if (nextProvider) {
        nextDraft = initialConfig
          ? {
              ...baseDraft,
              provider: nextProvider.id,
              providerKind: nextProvider.kind,
              apiFamily: nextProvider.apiFamily ?? baseDraft.apiFamily,
              apiUrl:
                nextProvider.kind === "cloud"
                  ? nextProvider.defaultBaseUrl
                  : baseDraft.apiUrl,
            }
          : {
              ...baseDraft,
              provider: nextProvider.id,
              providerKind: nextProvider.kind,
              apiFamily:
                nextProvider.apiFamily ?? DEFAULT_MODEL_API_FAMILY,
              apiUrl: nextProvider.defaultBaseUrl,
              supportsTools: nextProvider.supportsTools,
              supportsStreaming: nextProvider.supportsStreaming,
            };
      }

      setDraft(nextDraft);
      setDiscoveredModels(discoveredFromConfig(initialConfig));
      setErrors({});
      setSubmitting(false);
      setDiscovering(false);
    }

    setOpen(nextOpen);
  }

  function renderTrigger(): ReactElement {
    if (!trigger) {
      return (
        <Button
          type="button"
          disabled={!providersLoaded}
          aria-busy={!providersLoaded}
        >
          {providersLoaded ? (
            <Plus data-icon="inline-start" />
          ) : (
            <Spinner data-icon="inline-start" aria-hidden="true" />
          )}
          {t.addModelConfig}
        </Button>
      );
    }

    if (isValidElement(trigger)) {
      return trigger;
    }

    return (
      <Button type="button" variant="outline">
        {trigger}
      </Button>
    );
  }

  function renderManualModelField(label: string): ReactElement {
    return (
      <Field data-invalid={Boolean(errors.model)}>
        <FormFieldLabel htmlFor="model-name" label={label} required />
        <Input
          id="model-name"
          name="model-name"
          autoComplete="off"
          value={draft.model}
          aria-invalid={Boolean(errors.model)}
          onChange={(event) => updateField("model", event.target.value)}
        />
        <FieldError>{errors.model}</FieldError>
      </Field>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextErrors = validateDraft(
      draft,
      selectedProvider,
      discoveredModels,
      t,
    );
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }
    if (!selectedProvider) {
      return;
    }

    const apiKey = draft.apiKey.trim();
    const providerKind = draft.providerKind;
    const supportsThinking = draft.supportsThinking;
    const thinkingEnabled =
      supportsThinking && (usesManualModelSettings || draft.thinkingEnabled);
    const nextConfig: Omit<ModelConfig, "id"> & { id?: string } = {
      ...(initialConfig?.id ? { id: initialConfig.id } : {}),
      provider: draft.provider,
      providerLabel: selectedProvider.label,
      iconProvider: selectedProvider.iconProvider,
      providerKind,
      apiFamily: draft.apiFamily,
      nickname: draft.nickname.trim(),
      apiKeyPreview: draft.apiKeyPreview.trim(),
      model: draft.model.trim(),
      apiUrl: providerKind === "cloud" ? cloudApiUrl : draft.apiUrl.trim(),
      temperature: null,
      topP: null,
      maxTokens:
        providerKind === "cloud"
          ? null
          : normalizeMaxTokens(Number(draft.maxTokens)),
      contextWindowTokens: Number(draft.contextWindowTokens),
      supportsImage: draft.supportsImage,
      supportsThinking,
      supportsTools: draft.supportsTools,
      supportsStreaming: draft.supportsStreaming,
      thinkingEnabled,
    };

    setSubmitting(true);
    try {
      const savedConfig = await saveModelConfig(nextConfig, apiKey || undefined);

      onSubmit(savedConfig);
      toast.success(
        mode === "create" ? t.modelConfigCreated : t.modelConfigUpdated,
        {
          closeButton: true,
        },
      );
      setOpen(false);
    } catch (error) {
      setErrors((current) => ({
        ...current,
        discovery:
          error instanceof Error ? error.message : t.validationRequired,
      }));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        asChild
        disabled={!providersLoaded}
        aria-busy={!providersLoaded}
      >
        {renderTrigger()}
      </DialogTrigger>
      <DialogContent
        closeLabel={t.close}
        className="overflow-hidden p-0 sm:max-w-xl"
      >
        <form
          className="flex max-h-[min(680px,calc(100dvh-2rem))] min-h-0 flex-col"
          onSubmit={handleSubmit}
        >
          <DialogHeader className="shrink-0 px-6 pt-6">
            <DialogTitle>
              {mode === "create" ? t.addModelConfig : t.editModelConfig}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {mode === "create" ? t.addModelConfig : t.editModelConfig}
            </DialogDescription>
          </DialogHeader>

          <FieldGroup
            aria-busy={!providersLoaded}
            className="min-h-0 flex-1 gap-5 overflow-y-auto overscroll-contain px-6 py-6"
          >
            {!providersLoaded ? (
              <span className="sr-only" role="status">
                {t.modelProvidersLoading}
              </span>
            ) : null}
            <Field data-invalid={Boolean(errors.provider)}>
              <div className="flex items-center justify-between gap-3">
                <FormFieldLabel
                  htmlFor="model-provider"
                  label={t.provider}
                  required
                />
                {!providersLoaded ? (
                  <Skeleton className="h-5 w-16" />
                ) : selectedProvider?.officialUrl ? (
                  <Button
                    asChild
                    variant="link"
                    size="sm"
                    className="h-auto p-0 text-muted-foreground"
                  >
                    <a
                      href={selectedProvider.officialUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink className="size-3" aria-hidden="true" />
                      {t.officialApiUrl}
                    </a>
                  </Button>
                ) : null}
              </div>
              {!providersLoaded ? (
                <Skeleton className="h-9 w-full" />
              ) : selectedProvider ? (
                <Select
                  value={selectedProvider.id}
                  onValueChange={handleProviderChange}
                >
                  <SelectTrigger id="model-provider" className="w-full">
                    <div className="flex min-w-0 flex-1 items-center gap-2 pr-2">
                      <ModelProviderIcon
                        provider={selectedProvider.iconProvider}
                        size={18}
                      />
                      <span className="min-w-0 flex-1 truncate text-left">
                        {providerDisplayLabel(selectedProvider, t)}
                      </span>
                      <ProviderKindBadge>
                        {providerKindLabel(selectedProvider, t)}
                      </ProviderKindBadge>
                    </div>
                  </SelectTrigger>
                  <SelectContent
                    className="max-h-[320px] min-w-[var(--radix-select-trigger-width)]"
                    position="popper"
                  >
                    <SelectGroup>
                      {cloudProviders.map((provider) => (
                        <SelectItem key={provider.id} value={provider.id}>
                          <span className="flex min-w-0 items-center gap-2">
                            <ModelProviderIcon
                              provider={provider.iconProvider}
                              size={18}
                            />
                            <span className="min-w-0 flex-1 truncate">
                              {providerDisplayLabel(provider, t)}
                            </span>
                            <span className="ml-auto">
                              <ProviderKindBadge>
                                {providerKindLabel(provider, t)}
                              </ProviderKindBadge>
                            </span>
                          </span>
                        </SelectItem>
                      ))}
                      {providers
                        .filter((provider) => provider.kind !== "cloud")
                        .map((provider) => (
                          <SelectItem key={provider.id} value={provider.id}>
                            <span className="flex min-w-0 items-center gap-2">
                              <ModelProviderIcon
                                provider={provider.iconProvider}
                                size={18}
                              />
                              <span className="min-w-0 flex-1 truncate">
                                {providerDisplayLabel(provider, t)}
                              </span>
                              <span className="ml-auto">
                                <ProviderKindBadge>
                                  {providerKindLabel(provider, t)}
                                </ProviderKindBadge>
                              </span>
                            </span>
                          </SelectItem>
                        ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  className="w-full justify-start text-muted-foreground"
                  disabled
                >
                  {t.modelProvidersLoadError}
                </Button>
              )}
              <FieldError>{errors.provider}</FieldError>
            </Field>

            {usesManualModelSettings ? renderManualModelField(t.model) : null}

            <Field>
              <FormFieldLabel
                htmlFor="model-nickname"
                label={usesManualModelSettings ? t.displayName : t.nickname}
              />
              <Input
                id="model-nickname"
                name="model-nickname"
                autoComplete="off"
                value={draft.nickname}
                placeholder={
                  usesManualModelSettings
                    ? t.placeholders.displayName
                    : t.placeholders.nickname
                }
                onChange={(event) => updateField("nickname", event.target.value)}
              />
            </Field>

            <Field data-invalid={Boolean(errors.apiKey)}>
              <FormFieldLabel
                htmlFor="model-api-key"
                label={t.apiKey}
                required={Boolean(selectedProvider?.authRequired)}
              />
              <Input
                id="model-api-key"
                name="model-api-key"
                type="password"
                autoComplete="off"
                value={draft.apiKey}
                placeholder={draft.apiKeyPreview.trim()}
                aria-invalid={Boolean(errors.apiKey)}
                onChange={(event) => handleApiKeyChange(event.target.value)}
              />
              <FieldError>{errors.apiKey}</FieldError>
            </Field>

            {providersLoaded && draft.providerKind !== "cloud" ? (
              <Field data-invalid={Boolean(errors.apiUrl)}>
                <FormFieldLabel
                  htmlFor="model-api-url"
                  label={t.apiUrl}
                  required
                />
                <Input
                  id="model-api-url"
                  name="model-api-url"
                  type="url"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  value={draft.apiUrl}
                  placeholder={t.placeholders.apiUrl}
                  aria-invalid={Boolean(errors.apiUrl)}
                  onChange={(event) => handleApiUrlChange(event.target.value)}
                />
                <FieldError>{errors.apiUrl}</FieldError>
              </Field>
            ) : null}

            {!providersLoaded ? (
              <Field>
                <FormFieldLabel
                  htmlFor="model-select"
                  label={t.model}
                  required
                />
                <div className="flex gap-3">
                  <Skeleton className="h-9 min-w-0 flex-1" />
                  <Skeleton className="h-9 w-24 shrink-0" />
                </div>
              </Field>
            ) : usesDiscoveredModelSelect ? (
              <Field
                data-invalid={Boolean(errors.model || errors.discovery)}
              >
                <div className="flex items-end gap-3">
                  <div className="flex min-w-0 flex-1 flex-col gap-3">
                    <FormFieldLabel
                      htmlFor="model-select"
                      label={t.model}
                      required
                    />
                    <Select
                      value={draft.model}
                      onValueChange={handleModelSelect}
                      disabled={
                        draft.providerKind === "cloud" &&
                        discoveredModels.length === 0
                      }
                    >
                      <SelectTrigger id="model-select" className="w-full">
                        <SelectValue placeholder={modelSelectPlaceholder}>
                          <span className="min-w-0 truncate">
                            {modelSelectPlaceholder}
                          </span>
                        </SelectValue>
                      </SelectTrigger>
                      <SelectContent
                        className="max-h-[280px] min-w-[var(--radix-select-trigger-width)]"
                        position="popper"
                      >
                        {discoveredModels.map((model) => (
                          <SelectItem key={model.id} value={model.id}>
                            <span className="flex min-w-0 flex-col">
                              <span className="truncate">{model.label}</span>
                              <span className="text-xs text-muted-foreground">
                                {model.contextWindowTokens} context
                                {model.supportsImage ? ` · ${t.imageInput}` : ""}
                                {model.supportsThinking ? ` · ${t.thinking}` : ""}
                              </span>
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  {canDiscoverModels ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="shrink-0"
                      disabled={discovering}
                      onClick={() => void handleDiscoverModels()}
                    >
                      {discovering ? (
                        <Spinner data-icon="inline-start" aria-label={t.fetchingModels} />
                      ) : null}
                      {discoveryButtonLabel}
                    </Button>
                  ) : null}
                </div>
                <FieldError>{errors.model}</FieldError>
                <FieldError>{errors.discovery}</FieldError>
              </Field>
            ) : usesManualModelSettings ? null : (
              <FieldGroup className="gap-3">
                {renderManualModelField(t.model)}
                <FieldError>{errors.discovery}</FieldError>
              </FieldGroup>
            )}

            {usesManualModelSettings ? (
              <FieldSet>
                <FieldLegend variant="label">{t.capabilities}</FieldLegend>
                <FieldGroup
                  data-slot="checkbox-group"
                  className="grid gap-3 sm:grid-cols-3"
                >
                  <Field orientation="horizontal">
                    <Checkbox
                      id="model-supports-image"
                      checked={draft.supportsImage}
                      onCheckedChange={(checked) =>
                        updateField("supportsImage", checked === true)
                      }
                    />
                    <FieldLabel htmlFor="model-supports-image" className="font-normal">
                      {t.visionCapability}
                    </FieldLabel>
                  </Field>
                  <Field orientation="horizontal">
                    <Checkbox
                      id="model-supports-thinking"
                      checked={draft.supportsThinking}
                      onCheckedChange={(checked) => {
                        const enabled = checked === true;
                        updateField("supportsThinking", enabled);
                        updateField("thinkingEnabled", enabled);
                      }}
                    />
                    <FieldLabel
                      htmlFor="model-supports-thinking"
                      className="font-normal"
                    >
                      {t.reasoningCapability}
                    </FieldLabel>
                  </Field>
                  <Field orientation="horizontal">
                    <Checkbox
                      id="model-supports-tools"
                      checked={draft.supportsTools}
                      onCheckedChange={(checked) =>
                        updateField("supportsTools", checked === true)
                      }
                    />
                    <FieldLabel
                      htmlFor="model-supports-tools"
                      className="min-w-0 font-normal"
                    >
                      {t.toolUseCapability}
                    </FieldLabel>
                  </Field>
                </FieldGroup>
              </FieldSet>
            ) : null}

            {usesManualModelSettings ? (
              <FieldSet>
                <FieldLegend variant="label">{t.advancedSettings}</FieldLegend>
                <FieldGroup className="grid gap-3 sm:grid-cols-2">
                  <Field data-invalid={Boolean(errors.contextWindowTokens)}>
                    <FormFieldLabel
                      htmlFor="model-context-window"
                      label={t.contextWindow}
                      required
                    />
                    <Input
                      id="model-context-window"
                      name="model-context-window"
                      inputMode="numeric"
                      value={draft.contextWindowTokens}
                      placeholder={t.placeholders.contextWindow}
                      aria-invalid={Boolean(errors.contextWindowTokens)}
                      onChange={(event) =>
                        updateField("contextWindowTokens", event.target.value)
                      }
                    />
                    <FieldError>{errors.contextWindowTokens}</FieldError>
                  </Field>
                  <Field data-invalid={Boolean(errors.maxTokens)}>
                    <FormFieldLabel
                      htmlFor="model-max-tokens"
                      label={t.maxTokens}
                    />
                    <Input
                      id="model-max-tokens"
                      name="model-max-tokens"
                      inputMode="numeric"
                      value={draft.maxTokens}
                      placeholder={t.placeholders.maxTokens}
                      aria-invalid={Boolean(errors.maxTokens)}
                      onChange={(event) =>
                        updateField("maxTokens", event.target.value)
                      }
                    />
                    <FieldError>{errors.maxTokens}</FieldError>
                  </Field>
                </FieldGroup>
              </FieldSet>
            ) : null}

            {draft.supportsThinking && !usesManualModelSettings ? (
              <Field orientation="horizontal">
                <Checkbox
                  id="model-thinking-enabled"
                  checked={draft.thinkingEnabled}
                  onCheckedChange={(checked) =>
                    updateField("thinkingEnabled", checked === true)
                  }
                />
                <FieldLabel htmlFor="model-thinking-enabled" className="font-normal">
                  {t.thinkingEnabled}
                </FieldLabel>
              </Field>
            ) : null}

            {draft.providerKind !== "cloud" && errors.discovery ? (
              <FieldError>{errors.discovery}</FieldError>
            ) : null}
          </FieldGroup>

          <DialogFooter className="shrink-0 px-6 pb-6">
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t.cancel}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={submitting || discovering || !selectedProvider}>
              {submitting ? (
                <Spinner data-icon="inline-start" aria-label={t.saving} />
              ) : null}
              {mode === "create" ? t.createModelConfig : t.saveModelConfig}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
