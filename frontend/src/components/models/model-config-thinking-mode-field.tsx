import {
  Field,
  FieldContent,
  FieldError,
  FieldLabel,
} from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import type { AppMessages } from "@/i18n";
import type { ThinkingMode } from "@/types/resume";

export function ModelConfigThinkingModeField({
  availableModes,
  error,
  messages,
  onChange,
  value,
}: {
  availableModes: readonly ThinkingMode[];
  error?: string;
  messages: AppMessages;
  onChange: (value: ThinkingMode) => void;
  value: ThinkingMode;
}) {
  const canDisableThinking = availableModes.includes("off");
  const controlId = "model-thinking-mode";
  const labelId = `${controlId}-label`;
  const errorId = `${controlId}-error`;

  return (
    <Field
      orientation="horizontal"
      data-disabled={!canDisableThinking || undefined}
      data-invalid={Boolean(error)}
    >
      <FieldContent>
        <FieldLabel id={labelId} htmlFor={controlId}>
          {messages.thinkingMode}
        </FieldLabel>
        <FieldError id={errorId}>{error}</FieldError>
      </FieldContent>
      <Switch
        id={controlId}
        aria-labelledby={labelId}
        checked={canDisableThinking ? value === "auto" : true}
        disabled={!canDisableThinking}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
        onCheckedChange={(checked) => {
          // Checked keeps reasoning on the provider's automatic behavior;
          // unchecked is the user's explicit request to omit reasoning.
          onChange(checked ? "auto" : "off");
        }}
      />
    </Field>
  );
}
