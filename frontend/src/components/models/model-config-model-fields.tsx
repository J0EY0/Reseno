import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
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
import { ModelConfigThinkingModeField } from "./model-config-thinking-mode-field";
import type { ModelConfigDialogController } from "./use-model-config-dialog";

import "./model-config-model-fields.css";

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
            <SelectTrigger
              id="model-select"
              className="w-full"
              aria-invalid={Boolean(errors.model || errors.discovery)}
            >
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
            id="model-discovery"
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
  const { draft, errors, selectedProvider, updateField } = controller;
  const usesManualSettings =
    Boolean(selectedProvider) && draft.providerKind !== "cloud";

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
                onCheckedChange={(checked) =>
                  updateField("supportsThinking", checked === true)
                }
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
          {draft.supportsThinking ? (
            <ModelConfigThinkingModeField
              value={draft.thinkingMode}
              availableModes={draft.availableThinkingModes}
              error={errors.thinkingMode}
              messages={messages}
              onChange={(value) => updateField("thinkingMode", value)}
            />
          ) : null}
        </FieldSet>
      ) : null}

      {draft.providerKind !== "cloud" && errors.discovery ? (
        <FieldError>{errors.discovery}</FieldError>
      ) : null}
    </>
  );
}

function CloudAdvancedSettingsField({
  controller,
  messages,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
}) {
  const { draft, errors, updateField } = controller;
  const [open, setOpen] = useState(
    Boolean(draft.maxTokens) || draft.thinkingMode === "off",
  );
  const contentRef = useRef<HTMLDivElement>(null);
  const revealOnOpenRef = useRef(false);
  const focusInvalidOutputInput = useCallback(
    (input: HTMLInputElement | null) => {
      // The callback ref runs when the newly opened content mounts and again
      // when maxTokens changes from valid to invalid. This makes the actual
      // field the final focus target without timing assumptions.
      if (input && errors.maxTokens) {
        input.focus({ preventScroll: true });
      }
    },
    [errors.maxTokens],
  );
  const revealOutputField = useCallback(() => {
    const content = contentRef.current;
    const viewport = content?.closest<HTMLElement>(
      '[data-slot="field-group"]',
    );
    if (!content || !viewport) {
      return;
    }

    const contentRect = content.getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    const edgePadding = 12;
    const lowerEdge = viewportRect.bottom - edgePadding;
    const upperEdge = viewportRect.top + edgePadding;
    const delta =
      contentRect.bottom > lowerEdge
        ? contentRect.bottom - lowerEdge
        : contentRect.top < upperEdge
          ? contentRect.top - upperEdge
          : 0;

    if (Math.abs(delta) < 1) {
      return;
    }

    viewport.scrollTo({
      top: viewport.scrollTop + delta,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, []);
  const advancedSettingsError = Boolean(
    errors.thinkingMode || errors.maxTokens,
  );
  const expanded = open || advancedSettingsError;

  useLayoutEffect(() => {
    if (
      !expanded ||
      (!revealOnOpenRef.current && !advancedSettingsError)
    ) {
      return;
    }

    revealOnOpenRef.current = false;
    revealOutputField();
  }, [advancedSettingsError, expanded, revealOutputField]);

  if (draft.providerKind !== "cloud" || !draft.model.trim()) {
    return null;
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen && !expanded) {
      revealOnOpenRef.current = true;
    } else if (!nextOpen) {
      revealOnOpenRef.current = false;
    }
    setOpen(nextOpen);
  }

  return (
    <Collapsible open={expanded} onOpenChange={handleOpenChange}>
      <CollapsibleTrigger asChild>
        <button
          id="model-output-settings"
          type="button"
          aria-controls="model-output-settings-content"
          aria-invalid={advancedSettingsError}
          className="group flex min-h-9 w-full cursor-pointer items-center justify-between gap-3 rounded-md py-2 text-left text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <span>{messages.advancedSettings}</span>
          <ChevronDown
            aria-hidden="true"
            className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-aria-expanded:rotate-180"
          />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent
        ref={contentRef}
        id="model-output-settings-content"
        aria-labelledby="model-output-settings"
        className="model-output-settings-content"
      >
        <FieldGroup className="model-output-settings-content-inner gap-5 pt-3">
          {draft.supportsThinking ? (
            <ModelConfigThinkingModeField
              value={draft.thinkingMode}
              availableModes={draft.availableThinkingModes}
              error={errors.thinkingMode}
              messages={messages}
              onChange={(value) => updateField("thinkingMode", value)}
            />
          ) : null}
          <Field
            orientation="horizontal"
            className="flex-wrap gap-x-3 gap-y-1.5"
            data-invalid={Boolean(errors.maxTokens)}
          >
            <ModelFormFieldLabel
              htmlFor="model-max-tokens"
              label={messages.maxTokens}
            />
            <Input
              ref={focusInvalidOutputInput}
              id="model-max-tokens"
              name="model-max-tokens"
              type="text"
              inputMode="numeric"
              autoComplete="off"
              value={draft.maxTokens}
              placeholder={messages.maxTokensAuto}
              aria-invalid={Boolean(errors.maxTokens)}
              className="w-32 max-w-[55%] shrink-0"
              aria-describedby={
                errors.maxTokens ? "model-max-tokens-error" : undefined
              }
              onChange={(event) => {
                // The field intentionally keeps the raw digit string while the
                // user edits. Frontend and backend validation remain the single
                // authority for positive integers and discovered model limits;
                // the native number input's steppers must not silently coerce it.
                // Keep the section open after updateField clears a validation
                // error, so correcting the first digit never hides the input.
                if (errors.maxTokens) {
                  setOpen(true);
                }
                updateField("maxTokens", event.target.value);
              }}
            />
            <FieldError
              id="model-max-tokens-error"
              className="basis-full"
            >
              {errors.maxTokens}
            </FieldError>
          </Field>
        </FieldGroup>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function ModelConfigModelFields({
  controller,
  messages,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
}) {
  const {
    draft,
    errors,
    modelOptionsLoading,
    selectedProvider,
  } = controller;
  const usesDiscoveredModelSelect =
    Boolean(selectedProvider) && draft.providerKind === "cloud";
  const usesManualSettings =
    Boolean(selectedProvider) && !usesDiscoveredModelSelect;

  return (
    <>
      {modelOptionsLoading ? (
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

      {!modelOptionsLoading ? (
        <CapabilityFields controller={controller} messages={messages} />
      ) : null}
      {!modelOptionsLoading ? (
        <CloudAdvancedSettingsField controller={controller} messages={messages} />
      ) : null}
    </>
  );
}
