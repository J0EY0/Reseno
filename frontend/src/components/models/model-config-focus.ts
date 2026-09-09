import type { ModelConfigDraft, ModelConfigErrors } from "./model-config-draft";

type ErrorField = keyof ModelConfigErrors;

// Keep validation focus aligned with the controls' visual order in each form variant.
const cloudFocusOrder: ReadonlyArray<readonly [ErrorField, readonly string[]]> =
  [
    ["provider", ["model-provider"]],
    ["apiFamily", ["model-provider"]],
    ["apiKey", ["model-api-key"]],
    ["model", ["model-select", "model-discovery"]],
    ["discovery", ["model-select", "model-discovery"]],
    ["thinkingMode", ["model-thinking-mode", "model-output-settings"]],
    // When the validation render has already opened the section, focus the
    // actual input. The always-mounted trigger remains a safe pre-commit fallback.
    ["maxTokens", ["model-max-tokens", "model-output-settings"]],
  ];

const localFocusOrder: ReadonlyArray<readonly [ErrorField, readonly string[]]> =
  [
    ["provider", ["model-provider"]],
    ["apiFamily", ["model-provider"]],
    ["model", ["model-name"]],
    ["apiKey", ["model-api-key"]],
    ["apiUrl", ["model-api-url"]],
    ["thinkingMode", ["model-thinking-mode", "model-output-settings"]],
    ["contextWindowTokens", ["model-context-window", "model-output-settings"]],
    ["maxTokens", ["model-max-tokens", "model-output-settings"]],
    ["temperature", ["model-temperature", "model-output-settings"]],
    ["topP", ["model-top-p", "model-output-settings"]],
  ];

export function focusFirstModelConfigError(
  root: ParentNode,
  errors: ModelConfigErrors,
  providerKind: ModelConfigDraft["providerKind"],
) {
  const focusOrder =
    providerKind === "cloud" ? cloudFocusOrder : localFocusOrder;

  for (const [field, elementIds] of focusOrder) {
    if (!errors[field]) {
      continue;
    }

    for (const elementId of elementIds) {
      const element = root.querySelector<HTMLElement>(`#${elementId}`);
      const isDisabled =
        element !== null && "disabled" in element && element.disabled === true;

      if (element && !isDisabled) {
        element.focus();
        return true;
      }
    }
  }

  return false;
}
