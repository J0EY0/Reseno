import { ExternalLink } from "lucide-react";

import { ModelProviderIcon } from "@/components/model-provider-icon";
import { Button } from "@/components/ui/button";
import { Field, FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { AppMessages } from "@/i18n";

import {
  providerDisplayLabel,
  providerKindLabel,
} from "./model-config-draft";
import {
  ModelFormFieldLabel,
  ProviderKindBadge,
} from "./model-config-field-labels";
import type { ModelConfigDialogController } from "./use-model-config-dialog";

function ProviderOption({
  controller,
  messages,
  providerId,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
  providerId: string;
}) {
  const provider = controller.providers.find((item) => item.id === providerId);

  if (!provider) {
    return null;
  }

  return (
    <SelectItem value={provider.id}>
      <span className="flex min-w-0 items-center gap-2">
        <ModelProviderIcon provider={provider.iconProvider} size={18} />
        <span className="min-w-0 flex-1 truncate">
          {providerDisplayLabel(provider, messages)}
        </span>
        <span className="ml-auto">
          <ProviderKindBadge>
            {providerKindLabel(provider, messages)}
          </ProviderKindBadge>
        </span>
      </span>
    </SelectItem>
  );
}

function ModelProviderField({
  controller,
  messages,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
}) {
  const { errors, providers, providersLoaded, selectedProvider } = controller;
  const providerIds = [
    ...providers.filter((provider) => provider.kind === "cloud"),
    ...providers.filter((provider) => provider.kind !== "cloud"),
  ].map((provider) => provider.id);

  return (
    <Field data-invalid={Boolean(errors.provider)}>
      <div className="flex items-center justify-between gap-3">
        <ModelFormFieldLabel
          htmlFor="model-provider"
          label={messages.provider}
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
              {messages.officialApiUrl}
            </a>
          </Button>
        ) : null}
      </div>

      {!providersLoaded ? (
        <Skeleton className="h-9 w-full" />
      ) : selectedProvider ? (
        <Select
          value={selectedProvider.id}
          onValueChange={controller.selectProvider}
        >
          <SelectTrigger
            id="model-provider"
            className="w-full"
            aria-invalid={Boolean(errors.provider)}
          >
            <div className="flex min-w-0 flex-1 items-center gap-2 pr-2">
              <ModelProviderIcon
                provider={selectedProvider.iconProvider}
                size={18}
              />
              <span className="min-w-0 flex-1 truncate text-left">
                {providerDisplayLabel(selectedProvider, messages)}
              </span>
              <ProviderKindBadge>
                {providerKindLabel(selectedProvider, messages)}
              </ProviderKindBadge>
            </div>
          </SelectTrigger>
          <SelectContent
            className="max-h-[320px] min-w-[var(--radix-select-trigger-width)]"
            position="popper"
          >
            <SelectGroup>
              {providerIds.map((providerId) => (
                <ProviderOption
                  key={providerId}
                  controller={controller}
                  messages={messages}
                  providerId={providerId}
                />
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
          {messages.modelProvidersLoadError}
        </Button>
      )}
      <FieldError>{errors.provider}</FieldError>
    </Field>
  );
}

export function ModelConfigProviderFields({
  controller,
  messages,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
}) {
  const { draft, errors, providersLoaded, selectedProvider, updateField } =
    controller;
  const usesManualSettings =
    Boolean(selectedProvider) && draft.providerKind !== "cloud";

  return (
    <>
      <ModelProviderField controller={controller} messages={messages} />

      {usesManualSettings ? (
        <Field data-invalid={Boolean(errors.model)}>
          <ModelFormFieldLabel
            htmlFor="model-name"
            label={messages.model}
            required
          />
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
      ) : null}

      <Field>
        <ModelFormFieldLabel
          htmlFor="model-nickname"
          label={usesManualSettings ? messages.displayName : messages.nickname}
        />
        <Input
          id="model-nickname"
          name="model-nickname"
          autoComplete="off"
          value={draft.nickname}
          placeholder={
            usesManualSettings
              ? messages.placeholders.displayName
              : messages.placeholders.nickname
          }
          onChange={(event) => updateField("nickname", event.target.value)}
        />
      </Field>

      <Field data-invalid={Boolean(errors.apiKey)}>
        <ModelFormFieldLabel
          htmlFor="model-api-key"
          label={messages.apiKey}
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
          onChange={(event) => updateField("apiKey", event.target.value)}
        />
        <FieldError>{errors.apiKey}</FieldError>
      </Field>

      {providersLoaded && draft.providerKind !== "cloud" ? (
        <Field data-invalid={Boolean(errors.apiUrl)}>
          <ModelFormFieldLabel
            htmlFor="model-api-url"
            label={messages.apiUrl}
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
            placeholder={messages.placeholders.apiUrl}
            aria-invalid={Boolean(errors.apiUrl)}
            onChange={(event) => updateField("apiUrl", event.target.value)}
          />
          <FieldError>{errors.apiUrl}</FieldError>
        </Field>
      ) : null}
    </>
  );
}
