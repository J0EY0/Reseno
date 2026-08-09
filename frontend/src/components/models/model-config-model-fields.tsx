import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";

import { ModelFormFieldLabel } from "./model-config-field-labels";
import type { ModelConfigDialogController } from "./use-model-config-dialog";

function DiscoveredModelField({
  controller,
  messages,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
}) {
  const {
    canDiscoverModels,
    discovering,
    discoveredModels,
    draft,
    errors,
    refreshModels,
    selectModel,
  } = controller;
  const placeholder = draft.model
    ? draft.model
    : discoveredModels.length > 0
      ? messages.modelDiscoverySelectFetched
      : messages.modelDiscoveryRequired;
  const discoveryLabel = discovering
    ? messages.fetchingModels
    : discoveredModels.length > 0
      ? messages.refreshModels
      : messages.fetchModels;

  return (
    <Field data-invalid={Boolean(errors.model || errors.discovery)}>
      <div className="flex items-end gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <ModelFormFieldLabel
            htmlFor="model-select"
            label={messages.model}
            required
          />
          <Select
            value={draft.model}
            onValueChange={selectModel}
            disabled={discoveredModels.length === 0}
          >
            <SelectTrigger id="model-select" className="w-full">
              <SelectValue placeholder={placeholder}>
                <span className="min-w-0 truncate">{placeholder}</span>
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
                      {model.supportsImage ? ` · ${messages.imageInput}` : ""}
                      {model.supportsThinking ? ` · ${messages.thinking}` : ""}
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
            onClick={() => void refreshModels()}
          >
            {discovering ? (
              <Spinner
                data-icon="inline-start"
                aria-label={messages.fetchingModels}
              />
            ) : null}
            {discoveryLabel}
          </Button>
        ) : null}
      </div>
      <FieldError>{errors.model}</FieldError>
      <FieldError>{errors.discovery}</FieldError>
    </Field>
  );
}

function CapabilityFields({
  controller,
  messages,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
}) {
  const { draft, errors, updateField } = controller;
  const usesManualSettings = draft.providerKind !== "cloud";

  return (
    <>
      {usesManualSettings ? (
        <FieldSet>
          <FieldLegend variant="label">{messages.capabilities}</FieldLegend>
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
              <FieldLabel
                htmlFor="model-supports-image"
                className="font-normal"
              >
                {messages.visionCapability}
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
                {messages.reasoningCapability}
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
                {messages.toolUseCapability}
              </FieldLabel>
            </Field>
          </FieldGroup>
        </FieldSet>
      ) : null}

      {usesManualSettings ? (
        <FieldSet>
          <FieldLegend variant="label">{messages.advancedSettings}</FieldLegend>
          <FieldGroup className="grid gap-3 sm:grid-cols-2">
            <Field data-invalid={Boolean(errors.contextWindowTokens)}>
              <ModelFormFieldLabel
                htmlFor="model-context-window"
                label={messages.contextWindow}
                required
              />
              <Input
                id="model-context-window"
                name="model-context-window"
                inputMode="numeric"
                value={draft.contextWindowTokens}
                placeholder={messages.placeholders.contextWindow}
                aria-invalid={Boolean(errors.contextWindowTokens)}
                onChange={(event) =>
                  updateField("contextWindowTokens", event.target.value)
                }
              />
              <FieldError>{errors.contextWindowTokens}</FieldError>
            </Field>
            <Field data-invalid={Boolean(errors.maxTokens)}>
              <ModelFormFieldLabel
                htmlFor="model-max-tokens"
                label={messages.maxTokens}
              />
              <Input
                id="model-max-tokens"
                name="model-max-tokens"
                inputMode="numeric"
                value={draft.maxTokens}
                placeholder={messages.placeholders.maxTokens}
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

      {draft.supportsThinking && !usesManualSettings ? (
        <Field orientation="horizontal">
          <Checkbox
            id="model-thinking-enabled"
            checked={draft.thinkingEnabled}
            onCheckedChange={(checked) =>
              updateField("thinkingEnabled", checked === true)
            }
          />
          <FieldLabel
            htmlFor="model-thinking-enabled"
            className="font-normal"
          >
            {messages.thinkingEnabled}
          </FieldLabel>
        </Field>
      ) : null}

      {draft.providerKind !== "cloud" && errors.discovery ? (
        <FieldError>{errors.discovery}</FieldError>
      ) : null}
    </>
  );
}

export function ModelConfigModelFields({
  controller,
  messages,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
}) {
  const { draft, errors, providersLoaded, selectedProvider } = controller;
  const usesDiscoveredModelSelect =
    Boolean(selectedProvider) && draft.providerKind === "cloud";
  const usesManualSettings =
    Boolean(selectedProvider) && !usesDiscoveredModelSelect;

  return (
    <>
      {!providersLoaded ? (
        <Field>
          <ModelFormFieldLabel
            htmlFor="model-select"
            label={messages.model}
            required
          />
          <div className="flex gap-3">
            <Skeleton className="h-9 min-w-0 flex-1" />
            <Skeleton className="h-9 w-24 shrink-0" />
          </div>
        </Field>
      ) : usesDiscoveredModelSelect ? (
        <DiscoveredModelField controller={controller} messages={messages} />
      ) : usesManualSettings ? null : (
        <FieldGroup className="gap-3">
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
              onChange={(event) =>
                controller.updateField("model", event.target.value)
              }
            />
            <FieldError>{errors.model}</FieldError>
          </Field>
          <FieldError>{errors.discovery}</FieldError>
        </FieldGroup>
      )}

      <CapabilityFields controller={controller} messages={messages} />
    </>
  );
}
