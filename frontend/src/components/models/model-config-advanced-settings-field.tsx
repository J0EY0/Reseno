import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Field, FieldError, FieldGroup } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { AppMessages } from "@/i18n";

import { ModelConfigContextWindowField } from "./model-config-context-window-field";
import { ModelFormFieldLabel } from "./model-config-field-labels";
import { focusFirstModelConfigError } from "./model-config-focus";
import { ModelConfigThinkingModeField } from "./model-config-thinking-mode-field";
import type { ModelConfigDialogController } from "./use-model-config-dialog";

import "./model-config-model-fields.css";

export function ModelConfigAdvancedSettingsField({
  controller,
  messages,
}: {
  controller: ModelConfigDialogController;
  messages: AppMessages;
}) {
  const { draft, errors, selectedProvider, updateField } = controller;
  const usesManualSettings = draft.providerKind !== "cloud";
  const usesSamplingSettings = draft.providerKind === "local";
  const [open, setOpen] = useState(
    Boolean(draft.maxTokens) ||
      draft.thinkingMode === "off" ||
      (usesSamplingSettings && Boolean(draft.temperature || draft.topP)),
  );
  const contentRef = useRef<HTMLDivElement>(null);
  const revealOnOpenRef = useRef(false);
  const previousErrorsRef = useRef<typeof errors>({});
  const revealOutputField = useCallback((target?: HTMLElement | null) => {
    const content = contentRef.current;
    const viewport = content?.closest<HTMLElement>(
      '[data-slot="field-group"]',
    );
    if (!content || !viewport) {
      return;
    }

    const contentRect = (target ?? content).getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    const edgePadding = 12;
    const lowerEdge = viewportRect.bottom - edgePadding;
    const upperEdge = viewportRect.top + edgePadding;
    const delta =
      contentRect.height > lowerEdge - upperEdge || contentRect.top < upperEdge
        ? contentRect.top - upperEdge
        : contentRect.bottom > lowerEdge
          ? contentRect.bottom - lowerEdge
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
    (usesManualSettings && errors.contextWindowTokens) ||
      (usesSamplingSettings && (errors.temperature || errors.topP)) ||
      errors.thinkingMode ||
      errors.maxTokens,
  );
  const expanded = open || advancedSettingsError;

  useLayoutEffect(() => {
    const previousErrors = previousErrorsRef.current;
    previousErrorsRef.current = errors;
    const newAdvancedError = Boolean(
      (usesManualSettings &&
        errors.contextWindowTokens &&
        errors.contextWindowTokens !== previousErrors.contextWindowTokens) ||
        (usesSamplingSettings &&
          ((errors.temperature && errors.temperature !== previousErrors.temperature) ||
            (errors.topP && errors.topP !== previousErrors.topP))) ||
        (errors.maxTokens && errors.maxTokens !== previousErrors.maxTokens) ||
        (errors.thinkingMode && errors.thinkingMode !== previousErrors.thinkingMode),
    );
    if (!expanded || (!revealOnOpenRef.current && !newAdvancedError)) {
      return;
    }

    revealOnOpenRef.current = false;
    const form = contentRef.current?.closest("form");
    if (advancedSettingsError && form) {
      focusFirstModelConfigError(form, errors, draft.providerKind);
      revealOutputField(
        document.activeElement instanceof HTMLElement
          ? document.activeElement.closest<HTMLElement>('[data-slot="field"]') ??
            document.activeElement
          : null,
      );
    } else {
      revealOutputField();
    }
  }, [
    advancedSettingsError,
    draft.providerKind,
    errors,
    expanded,
    revealOutputField,
    usesManualSettings,
    usesSamplingSettings,
  ]);

  if (!selectedProvider || (!usesManualSettings && !draft.model.trim())) {
    return null;
  }

  const updateAdvancedField: typeof updateField = (field, value) => {
    setOpen(true);
    updateField(field, value);
  };

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
              onChange={(value) => updateAdvancedField("thinkingMode", value)}
            />
          ) : null}
          {usesManualSettings ? (
            <ModelConfigContextWindowField
              key={JSON.stringify([draft.provider, draft.model])}
              provider={draft.provider}
              model={draft.model}
              value={draft.contextWindowTokens}
              error={errors.contextWindowTokens}
              messages={messages}
              onChange={(value) => updateAdvancedField("contextWindowTokens", value)}
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
              onChange={(event) =>
                updateAdvancedField("maxTokens", event.target.value)
              }
            />
            <FieldError
              id="model-max-tokens-error"
              className="basis-full"
            >
              {errors.maxTokens}
            </FieldError>
          </Field>
          {usesSamplingSettings
            ? (["temperature", "topP"] as const).map((field) => {
                const id = field === "temperature" ? "model-temperature" : "model-top-p";
                const error = errors[field];

                return (
                  <Field
                    key={field}
                    orientation="horizontal"
                    className="flex-wrap gap-x-3 gap-y-1.5"
                    data-invalid={Boolean(error)}
                  >
                    <ModelFormFieldLabel htmlFor={id} label={messages[field]} />
                    <Input
                      id={id}
                      name={id}
                      type="text"
                      inputMode="decimal"
                      autoComplete="off"
                      value={draft[field]}
                      aria-invalid={Boolean(error)}
                      aria-describedby={error ? `${id}-error` : undefined}
                      className="w-32 max-w-[55%] shrink-0"
                      onChange={(event) => updateAdvancedField(field, event.target.value)}
                    />
                    <FieldError id={`${id}-error`} className="basis-full">
                      {error}
                    </FieldError>
                  </Field>
                );
              })
            : null}
        </FieldGroup>
      </CollapsibleContent>
    </Collapsible>
  );
}
