import { ExternalLink, Pencil, Plus, X } from "lucide-react";
import {
  isValidElement,
  useState,
  type FormEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import type { AppMessages, Locale } from "@/i18n";
import {
  clampTemperature,
  clampTopP,
  createDefaultModelConfig,
  normalizeMaxTokens,
} from "@/lib/model-config";
import { saveModelConfig } from "@/lib/model-config-api";
import {
  getModelProviderMeta,
  getProviderApiUrl,
  getProviderDefaultModel,
  isProviderApiKeyRequired,
  MODEL_PROVIDERS,
} from "@/lib/model-providers";
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
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";

type ModelConfigDraft = Omit<ModelConfig, "id" | "maxTokens"> & {
  apiKey: string;
  maxTokens: string;
};
type ModelConfigErrors = Partial<Record<keyof ModelConfigDraft, string>>;

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

function isValidTemperature(value: number) {
  return (
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1 &&
    Math.abs(value * 10 - Math.round(value * 10)) < 1e-6
  );
}

function isValidTopP(value: number) {
  return Number.isFinite(value) && value >= 0 && value <= 1;
}

function isValidMaxTokens(value: string) {
  const trimmed = value.trim();

  if (!trimmed) {
    return true;
  }

  return /^\d+$/.test(trimmed) && Number(trimmed) > 0;
}

function validateDraft(
  draft: ModelConfigDraft,
  t: AppMessages,
): ModelConfigErrors {
  const errors: ModelConfigErrors = {};

  if (!draft.provider.trim()) {
    errors.provider = t.validationRequired;
  }

  if (!draft.model.trim()) {
    errors.model = t.validationRequired;
  }

  if (
    isProviderApiKeyRequired(draft.provider) &&
    !draft.apiKey.trim() &&
    !draft.apiKeyPreview.trim()
  ) {
    errors.apiKey = t.validationRequired;
  }

  if (!draft.apiUrl.trim()) {
    errors.apiUrl = t.validationRequired;
  } else if (!isValidHttpUrl(draft.apiUrl.trim())) {
    errors.apiUrl = t.validationApiUrl;
  }

  if (!isValidTemperature(draft.temperature)) {
    errors.temperature = t.validationTemperature;
  }

  if (!isValidTopP(draft.topP)) {
    errors.topP = t.validationTopP;
  }

  if (!isValidMaxTokens(draft.maxTokens)) {
    errors.maxTokens = t.validationMaxTokens;
  }

  return errors;
}

function toDraft(locale: Locale, config?: ModelConfig): ModelConfigDraft {
  const fallback = createDefaultModelConfig(locale);

  return {
    provider: config?.provider ?? fallback.provider,
    nickname: config?.nickname ?? fallback.nickname,
    apiKeyPreview: config?.apiKeyPreview ?? fallback.apiKeyPreview,
    apiKey: "",
    model: config?.model ?? fallback.model,
    apiUrl: config?.apiUrl ?? fallback.apiUrl,
    temperature: config?.temperature ?? fallback.temperature,
    topP: config?.topP ?? fallback.topP,
    maxTokens:
      typeof config?.maxTokens === "number" ? String(config.maxTokens) : "",
    contextWindowTokens:
      config?.contextWindowTokens ?? fallback.contextWindowTokens,
    systemPrompt: config?.systemPrompt ?? fallback.systemPrompt,
  };
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
  const [draft, setDraft] = useState<ModelConfigDraft>(() =>
    toDraft(locale, initialConfig),
  );
  const [errors, setErrors] = useState<ModelConfigErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const selectedProvider = getModelProviderMeta(draft.provider);

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

  function handleTemperatureInput(value: string) {
    if (!value.trim()) {
      updateField("temperature", 0);
      return;
    }

    const nextValue = Number(value);

    if (!Number.isFinite(nextValue)) {
      return;
    }

    updateField("temperature", clampTemperature(nextValue));
  }

  function handleTopPInput(value: string) {
    if (!value.trim()) {
      updateField("topP", 0);
      return;
    }

    const nextValue = Number(value);

    if (!Number.isFinite(nextValue)) {
      return;
    }

    updateField("topP", clampTopP(nextValue));
  }

  function handleMaxTokensInput(value: string) {
    if (!/^\d*$/.test(value)) {
      return;
    }

    updateField("maxTokens", value);
  }

  function handleProviderChange(nextProvider: string) {
    setDraft((current) => {
      const currentProvider = getModelProviderMeta(current.provider);
      const nextProviderMeta = getModelProviderMeta(nextProvider);
      const shouldReplaceApiUrl =
        !current.apiUrl.trim() || current.apiUrl === currentProvider.apiUrl;
      const shouldReplaceModel =
        !current.model.trim() || current.model === currentProvider.defaultModel;

      return {
        ...current,
        provider: nextProviderMeta.id,
        model: shouldReplaceModel
          ? getProviderDefaultModel(nextProviderMeta.id)
          : current.model,
        apiUrl: shouldReplaceApiUrl
          ? getProviderApiUrl(nextProviderMeta.id)
          : current.apiUrl,
        apiKeyPreview:
          nextProviderMeta.id === currentProvider.id ? current.apiKeyPreview : "",
      };
    });
    setErrors((current) => {
      const next = { ...current };
      delete next.provider;
      delete next.model;
      delete next.apiUrl;
      delete next.apiKey;
      return next;
    });
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      setDraft(toDraft(locale, initialConfig));
      setErrors({});
      setSubmitting(false);
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextErrors = validateDraft(draft, t);

    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }

    const maxTokens = draft.maxTokens.trim()
      ? normalizeMaxTokens(Number(draft.maxTokens))
      : null;
    const apiKey = draft.apiKey.trim();
    setSubmitting(true);

    try {
      const savedConfig = await saveModelConfig(
        {
          ...(initialConfig?.id ? { id: initialConfig.id } : {}),
          provider: draft.provider,
          nickname: draft.nickname.trim(),
          apiKeyPreview: draft.apiKeyPreview.trim(),
          model: draft.model.trim(),
          apiUrl: draft.apiUrl.trim(),
          temperature: clampTemperature(Number(draft.temperature)),
          topP: clampTopP(Number(draft.topP)),
          maxTokens,
          contextWindowTokens: draft.contextWindowTokens,
          systemPrompt: draft.systemPrompt.trim(),
        },
        apiKey || undefined,
      );

      onSubmit({
        id: savedConfig.id,
        provider: savedConfig.provider,
        nickname: savedConfig.nickname,
        apiKeyPreview: savedConfig.apiKeyPreview,
        model: savedConfig.model,
        apiUrl: savedConfig.apiUrl,
        temperature: savedConfig.temperature,
        topP: savedConfig.topP,
        maxTokens: savedConfig.maxTokens,
        contextWindowTokens: savedConfig.contextWindowTokens,
        systemPrompt: savedConfig.systemPrompt,
      });
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
        apiKey:
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
        className="max-h-[min(680px,calc(100dvh-2rem))] w-[min(600px,calc(100vw-2rem))] overflow-hidden border-border/70 bg-background/95 p-0 shadow-[0_30px_100px_rgba(0,0,0,0.24)] backdrop-blur-xl"
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
                <a
                  href={selectedProvider.officialUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70"
                >
                  <ExternalLink className="size-3" aria-hidden="true" />
                  {t.officialApiUrl}
                </a>
              </div>
              <Select
                value={selectedProvider.id}
                onValueChange={handleProviderChange}
              >
                <SelectTrigger
                  className="h-[52px] w-full rounded-[1.35rem] border-border/70 bg-background/85 px-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_12px_34px_rgba(0,0,0,0.055)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                  aria-invalid={Boolean(errors.provider)}
                >
                  <div className="flex min-w-0 flex-1 items-center gap-2 pr-2">
                    <ModelProviderIcon
                      provider={selectedProvider.iconProvider}
                      size={22}
                    />
                    <span className="min-w-0 flex-1 truncate text-left">
                      {selectedProvider.label}
                    </span>
                    <span className="shrink-0 rounded-full border border-border/60 bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground">
                      {selectedProvider.local ? t.localProvider : t.cloudProvider}
                    </span>
                  </div>
                </SelectTrigger>
                <SelectContent
                  className="max-h-[320px] min-w-[var(--radix-select-trigger-width)]"
                  portalled={false}
                  position="popper"
                >
                  <SelectGroup>
                    {MODEL_PROVIDERS.map((provider) => (
                      <SelectItem key={provider.id} value={provider.id}>
                        <span className="flex min-w-0 items-center gap-2">
                          <ModelProviderIcon
                            provider={provider.iconProvider}
                            size={18}
                          />
                          <span className="min-w-0 flex-1 truncate">
                            {provider.label}
                          </span>
                          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                            {provider.local ? t.localProvider : t.cloudProvider}
                          </span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              {errors.provider ? (
                <p className="text-xs text-destructive">{errors.provider}</p>
              ) : null}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-2 text-sm">
                <FieldLabel label={t.nickname} />
                <Input
                  className="h-12 rounded-[1.25rem] border-border/60 bg-background/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                  name="model-nickname"
                  autoComplete="off"
                  value={draft.nickname}
                  placeholder={t.placeholders.nickname}
                  aria-invalid={Boolean(errors.nickname)}
                  onChange={(event) =>
                    updateField("nickname", event.target.value)
                  }
                />
                {errors.nickname ? (
                  <p className="text-xs text-destructive">{errors.nickname}</p>
                ) : null}
              </label>

              <label className="grid gap-2 text-sm">
                <FieldLabel label={t.model} required />
                <Input
                  className="h-12 rounded-[1.25rem] border-border/60 bg-background/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
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
            </div>

            <label className="grid gap-2 text-sm">
              <FieldLabel
                label={t.apiKey}
                required={selectedProvider.authRequired}
              />
              <Input
                className="h-12 rounded-[1.25rem] border-border/60 bg-background/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                name="model-api-key"
                type="password"
                autoComplete="off"
                value={draft.apiKey}
                placeholder={draft.apiKeyPreview.trim()}
                aria-invalid={Boolean(errors.apiKey)}
                onChange={(event) => updateField("apiKey", event.target.value)}
              />
              {errors.apiKey ? (
                <p className="text-xs text-destructive">{errors.apiKey}</p>
              ) : null}
            </label>

            <label className="grid gap-2 text-sm">
              <FieldLabel label={t.apiUrl} required />
              <Input
                className="h-12 rounded-[1.25rem] border-border/60 bg-background/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                name="model-api-url"
                type="url"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                value={draft.apiUrl}
                placeholder={t.placeholders.apiUrl}
                aria-invalid={Boolean(errors.apiUrl)}
                onChange={(event) => updateField("apiUrl", event.target.value)}
              />
              {errors.apiUrl ? (
                <p className="text-xs text-destructive">{errors.apiUrl}</p>
              ) : null}
            </label>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-2 text-sm">
                <FieldLabel label={t.maxTokens} />
                <Input
                  className="h-12 rounded-[1.25rem] border-border/60 bg-background/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                  name="model-max-tokens"
                  type="number"
                  inputMode="numeric"
                  min="1"
                  step="1"
                  autoComplete="off"
                  value={draft.maxTokens}
                  aria-invalid={Boolean(errors.maxTokens)}
                  onChange={(event) => handleMaxTokensInput(event.target.value)}
                />
                {errors.maxTokens ? (
                  <p className="text-xs text-destructive">{errors.maxTokens}</p>
                ) : null}
              </label>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-[1.35rem] border border-border/50 bg-gradient-to-br from-muted/35 via-background to-muted/20 p-4 text-sm shadow-sm shadow-black/[0.03]">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <FieldLabel label={t.temperature} />
                  <Input
                    className="h-9 w-20 rounded-xl bg-background text-center tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                    name="model-temperature"
                    type="number"
                    inputMode="decimal"
                    min="0"
                    max="1"
                    step="0.1"
                    value={draft.temperature}
                    aria-invalid={Boolean(errors.temperature)}
                    onChange={(event) =>
                      handleTemperatureInput(event.target.value)
                    }
                  />
                </div>
                <div className="px-1">
                  <Slider
                    min={0}
                    max={1}
                    step={0.1}
                    value={[draft.temperature]}
                    onValueChange={(value) =>
                      updateField(
                        "temperature",
                        clampTemperature(value[0] ?? 0),
                      )
                    }
                  />
                </div>
                {errors.temperature ? (
                  <p className="mt-2 text-xs text-destructive">
                    {errors.temperature}
                  </p>
                ) : null}
              </div>

              <div className="rounded-[1.35rem] border border-border/50 bg-gradient-to-br from-muted/35 via-background to-muted/20 p-4 text-sm shadow-sm shadow-black/[0.03]">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <FieldLabel label={t.topP} />
                  <Input
                    className="h-9 w-20 rounded-xl bg-background text-center tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                    name="model-top-p"
                    type="number"
                    inputMode="decimal"
                    min="0"
                    max="1"
                    step="0.01"
                    value={draft.topP}
                    aria-invalid={Boolean(errors.topP)}
                    onChange={(event) => handleTopPInput(event.target.value)}
                  />
                </div>
                <div className="px-1">
                  <Slider
                    min={0}
                    max={1}
                    step={0.01}
                    value={[draft.topP]}
                    onValueChange={(value) =>
                      updateField("topP", clampTopP(value[0] ?? 0))
                    }
                  />
                </div>
                {errors.topP ? (
                  <p className="mt-2 text-xs text-destructive">{errors.topP}</p>
                ) : null}
              </div>
            </div>
          </div>

          <DialogFooter className="shrink-0 border-t border-border/70 bg-background/90 px-6 py-4 backdrop-blur">
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t.cancel}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={submitting}>
              {mode === "create" ? t.createModelConfig : t.saveModelConfig}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
