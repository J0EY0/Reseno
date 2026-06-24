import { ExternalLink, Pencil, Plus, X } from "lucide-react";
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
import { Button } from "@/components/ui/button";
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
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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

const PROVIDER_KIND_TAG_CLASS_NAME =
  "shrink-0 rounded-full border border-border/60 bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground";

const CAPABILITY_CHECKBOX_CLASS_NAME =
  "size-5 shrink-0 rounded-md border border-border/70 accent-foreground";

function FieldLabel({
  label,
  required = false,
}: {
  label: string;
  required?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1 font-medium">
      <span>{label}</span>
      {required ? <span className="text-destructive">*</span> : null}
    </span>
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
  return providers.find((provider) => provider.id === providerId) ?? providers[0] ?? null;
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
    contextWindowTokens: String(source.contextWindowTokens || 32768),
    supportsImage: source.supportsImage,
    supportsThinking: source.supportsThinking,
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
              contextWindowTokens: "32768",
              supportsImage: false,
              supportsThinking: false,
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
    if (!open) {
      return;
    }

    void getModelProviders()
      .then((response) => {
        const nextProviders = response.providers;
        setProviders(nextProviders);
        setProvidersLoaded(true);
        setDraft((current) => {
          const nextProvider = providerById(nextProviders, current.provider);

          if (!nextProvider) {
            return current;
          }

          if (initialConfig) {
            return {
              ...current,
              provider: nextProvider.id,
              providerKind: nextProvider.kind,
              apiFamily: nextProvider.apiFamily ?? current.apiFamily,
              apiUrl:
                nextProvider.kind === "cloud"
                  ? nextProvider.defaultBaseUrl
                  : current.apiUrl,
            };
          }

          return {
            ...current,
            provider: nextProvider.id,
            providerKind: nextProvider.kind,
            apiFamily: nextProvider.apiFamily ?? "openai_compatible_chat",
            apiUrl: nextProvider.defaultBaseUrl,
          };
        });
      })
      .catch((error) => {
        console.error("Failed to load model providers.", error);
        setProvidersLoaded(true);
      });
  }, [initialConfig, open]);

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

    const nextApiFamily =
      nextProviderMeta.apiFamily ?? "openai_compatible_chat";

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
      contextWindowTokens: "32768",
      supportsImage: false,
      supportsThinking: false,
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
      setDraft(toDraft(locale, initialConfig));
      setDiscoveredModels(discoveredFromConfig(initialConfig));
      setErrors({});
      setSubmitting(false);
      setDiscovering(false);
      setProviders([]);
      setProvidersLoaded(false);
    }

    setOpen(nextOpen);
  }

  function renderTrigger(): ReactElement {
    if (!trigger) {
      return (
        <Button type="button" className="gap-2">
          <Plus className="size-4" />
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
      <label className="grid gap-2 text-sm">
        <FieldLabel label={label} required />
        <Input
          className="h-12 rounded-[1.25rem] border-border/60 bg-background/80"
          name="model-name"
          autoComplete="off"
          value={draft.model}
          placeholder={t.placeholders.modelName}
          aria-invalid={Boolean(errors.model)}
          onChange={(event) => updateField("model", event.target.value)}
        />
        {errors.model ? (
          <p className="text-xs text-destructive">{errors.model}</p>
        ) : null}
      </label>
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
      <DialogTrigger asChild>{renderTrigger()}</DialogTrigger>
      <DialogContent
        showCloseButton={false}
        className="max-h-[min(680px,calc(100dvh-2rem))] w-[min(600px,calc(100vw-2rem))] overflow-hidden border-border/70 bg-background p-0 shadow-[0_30px_100px_rgba(0,0,0,0.24)]"
      >
        <form
          className="flex max-h-[min(680px,calc(100dvh-2rem))] min-h-0 flex-col"
          onSubmit={handleSubmit}
        >
          <DialogHeader className="relative shrink-0 overflow-hidden border-b border-border/70 px-6 py-4 pr-14">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_12%_10%,rgba(0,0,0,0.10),transparent_28%),linear-gradient(135deg,rgba(0,0,0,0.045),transparent_48%)]" />
            <div className="pointer-events-none absolute inset-0 opacity-45 [background-image:linear-gradient(rgba(0,0,0,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(0,0,0,0.035)_1px,transparent_1px)] [background-size:28px_28px]" />
            <div className="relative flex items-center gap-4">
              <div className="relative flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-foreground text-background shadow-[0_14px_30px_rgba(0,0,0,0.18)]">
                <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.18),transparent_45%)]" />
                {mode === "create" ? (
                  <Plus className="relative size-5" aria-hidden="true" />
                ) : (
                  <Pencil className="relative size-5" aria-hidden="true" />
                )}
              </div>
              <div className="min-w-0">
                <DialogTitle className="text-lg font-semibold tracking-tight">
                  {mode === "create" ? t.addModelConfig : t.editModelConfig}
                </DialogTitle>
                <DialogDescription className="sr-only">
                  {mode === "create" ? t.addModelConfig : t.editModelConfig}
                </DialogDescription>
              </div>
            </div>
            <DialogClose
              className="absolute right-4 top-1/2 z-10 inline-flex size-9 -translate-y-1/2 items-center justify-center rounded-xl bg-background/55 text-muted-foreground transition-colors duration-200 hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70"
              aria-label="Close"
            >
              <X className="size-[18px]" aria-hidden="true" />
            </DialogClose>
          </DialogHeader>

          <div className="min-h-0 max-h-[500px] space-y-4 overflow-y-auto overscroll-contain bg-[radial-gradient(circle_at_top_right,rgba(0,0,0,0.055),transparent_34%),linear-gradient(180deg,rgba(0,0,0,0.025),transparent_24%)] px-6 py-4">
            <div className="grid gap-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <FieldLabel label={t.provider} required />
                {selectedProvider?.officialUrl ? (
                  <a
                    href={selectedProvider.officialUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70"
                  >
                    <ExternalLink className="size-3" aria-hidden="true" />
                    {t.officialApiUrl}
                  </a>
                ) : null}
              </div>
              {selectedProvider ? (
                <Select
                  value={selectedProvider.id}
                  onValueChange={handleProviderChange}
                >
                  <SelectTrigger className="h-[52px] w-full rounded-[1.35rem] border-border/70 bg-background/85 px-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_12px_34px_rgba(0,0,0,0.055)]">
                    <div className="flex min-w-0 flex-1 items-center gap-2 pr-2">
                      <ModelProviderIcon
                        provider={selectedProvider.iconProvider}
                        size={22}
                      />
                      <span className="min-w-0 flex-1 truncate text-left">
                        {providerDisplayLabel(selectedProvider, t)}
                      </span>
                      <span className={PROVIDER_KIND_TAG_CLASS_NAME}>
                        {providerKindLabel(selectedProvider, t)}
                      </span>
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
                            <span className={`ml-auto ${PROVIDER_KIND_TAG_CLASS_NAME}`}>
                              {providerKindLabel(provider, t)}
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
                              <span className={`ml-auto ${PROVIDER_KIND_TAG_CLASS_NAME}`}>
                                {providerKindLabel(provider, t)}
                              </span>
                            </span>
                          </SelectItem>
                        ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              ) : (
                <button
                  type="button"
                  className="flex h-[52px] w-full items-center rounded-[1.35rem] border border-border/70 bg-background/85 px-3 text-left text-sm text-muted-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_12px_34px_rgba(0,0,0,0.055)]"
                  disabled
                >
                  {providersLoaded ? t.loadError : t.loading}
                </button>
              )}
              {errors.provider ? (
                <p className="text-xs text-destructive">{errors.provider}</p>
              ) : null}
            </div>

            {usesManualModelSettings ? (
              renderManualModelField(t.modelId)
            ) : null}

            <label className="grid gap-2 text-sm">
              <FieldLabel
                label={usesManualModelSettings ? t.displayName : t.nickname}
              />
              <Input
                className="h-12 rounded-[1.25rem] border-border/60 bg-background/80"
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
            </label>

            <label className="grid gap-2 text-sm">
              <FieldLabel
                label={t.apiKey}
                required={Boolean(selectedProvider?.authRequired)}
              />
              <Input
                className="h-12 rounded-[1.25rem] border-border/60 bg-background/80"
                name="model-api-key"
                type="password"
                autoComplete="off"
                value={draft.apiKey}
                placeholder={draft.apiKeyPreview.trim()}
                aria-invalid={Boolean(errors.apiKey)}
                onChange={(event) => handleApiKeyChange(event.target.value)}
              />
              {errors.apiKey ? (
                <p className="text-xs text-destructive">{errors.apiKey}</p>
              ) : null}
            </label>

            {draft.providerKind !== "cloud" ? (
              <label className="grid gap-2 text-sm">
                <FieldLabel label={t.apiUrl} required />
                <Input
                  className="h-12 rounded-[1.25rem] border-border/60 bg-background/80"
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
                {errors.apiUrl ? (
                  <p className="text-xs text-destructive">{errors.apiUrl}</p>
                ) : null}
              </label>
            ) : null}

            {usesDiscoveredModelSelect ? (
              <div className="grid gap-3 text-sm">
                <div className="flex items-end gap-3">
                  <div className="grid min-w-0 flex-1 gap-2">
                    <FieldLabel label={t.model} required />
                    <Select
                      value={draft.model}
                      onValueChange={handleModelSelect}
                      disabled={
                        draft.providerKind === "cloud" &&
                        discoveredModels.length === 0
                      }
                    >
                      <SelectTrigger className="h-12 w-full rounded-[1.25rem] border-border/60 bg-background/80">
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
                      className="h-12 shrink-0 rounded-[1.25rem]"
                      disabled={discovering}
                      onClick={() => void handleDiscoverModels()}
                    >
                      {discoveryButtonLabel}
                    </Button>
                  ) : null}
                </div>
                {errors.model ? (
                  <p className="text-xs text-destructive">{errors.model}</p>
                ) : null}
                {errors.discovery ? (
                  <p className="text-xs text-destructive">{errors.discovery}</p>
                ) : null}
              </div>
            ) : usesManualModelSettings ? null : (
              <div className="grid gap-3 text-sm">
                {renderManualModelField(t.model)}
                {errors.discovery ? (
                  <p className="text-xs text-destructive">{errors.discovery}</p>
                ) : null}
              </div>
            )}

            {usesManualModelSettings ? (
              <div className="grid gap-3 text-sm">
                <div className="font-medium">{t.capabilities}</div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="flex h-11 items-center gap-3 rounded-xl border border-border/60 bg-background/80 px-3">
                    <input
                      className={CAPABILITY_CHECKBOX_CLASS_NAME}
                      type="checkbox"
                      checked={draft.supportsImage}
                      onChange={(event) =>
                        updateField("supportsImage", event.target.checked)
                      }
                    />
                    <span>{t.visionCapability}</span>
                  </label>
                  <label className="flex h-11 items-center gap-3 rounded-xl border border-border/60 bg-background/80 px-3">
                    <input
                      className={CAPABILITY_CHECKBOX_CLASS_NAME}
                      type="checkbox"
                      checked={draft.supportsThinking}
                      onChange={(event) => {
                        updateField("supportsThinking", event.target.checked);
                        updateField("thinkingEnabled", event.target.checked);
                      }}
                    />
                    <span>{t.reasoningCapability}</span>
                  </label>
                  <label className="flex h-11 items-center gap-3 rounded-xl border border-border/60 bg-background/80 px-3">
                    <input
                      className={CAPABILITY_CHECKBOX_CLASS_NAME}
                      type="checkbox"
                      checked
                      readOnly
                      aria-readonly="true"
                    />
                    <span className="min-w-0 flex-1 truncate">
                      {t.toolUseCapability}
                    </span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {t.requiredCapability}
                    </span>
                  </label>
                </div>
              </div>
            ) : null}

            {usesManualModelSettings ? (
              <div className="grid gap-3 text-sm">
                <div className="font-medium">{t.advancedSettings}</div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="grid gap-2">
                    <FieldLabel label={t.contextWindow} required />
                    <Input
                      className="h-11 rounded-xl"
                      name="model-context-window"
                      inputMode="numeric"
                      value={draft.contextWindowTokens}
                      placeholder={t.placeholders.contextWindow}
                      aria-invalid={Boolean(errors.contextWindowTokens)}
                      onChange={(event) =>
                        updateField("contextWindowTokens", event.target.value)
                      }
                    />
                    {errors.contextWindowTokens ? (
                      <p className="text-xs text-destructive">
                        {errors.contextWindowTokens}
                      </p>
                    ) : null}
                  </label>
                  <label className="grid gap-2">
                    <FieldLabel label={t.maxTokens} />
                    <Input
                      className="h-11 rounded-xl"
                      name="model-max-tokens"
                      inputMode="numeric"
                      value={draft.maxTokens}
                      placeholder={t.placeholders.maxTokens}
                      aria-invalid={Boolean(errors.maxTokens)}
                      onChange={(event) =>
                        updateField("maxTokens", event.target.value)
                      }
                    />
                    {errors.maxTokens ? (
                      <p className="text-xs text-destructive">
                        {errors.maxTokens}
                      </p>
                    ) : null}
                  </label>
                </div>
              </div>
            ) : null}

            {draft.supportsThinking && !usesManualModelSettings ? (
              <div className="rounded-[1.35rem] border border-border/50 bg-background/65 p-4 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={draft.thinkingEnabled}
                    onChange={(event) =>
                      updateField("thinkingEnabled", event.target.checked)
                    }
                  />
                  <span>{t.thinkingEnabled}</span>
                </label>
              </div>
            ) : null}

            {draft.providerKind !== "cloud" && errors.discovery ? (
              <p className="text-xs text-destructive">{errors.discovery}</p>
            ) : null}
          </div>

          <DialogFooter className="shrink-0 border-t border-border/70 bg-background px-6 py-4">
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t.cancel}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={submitting || discovering || !selectedProvider}>
              {mode === "create" ? t.createModelConfig : t.saveModelConfig}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
