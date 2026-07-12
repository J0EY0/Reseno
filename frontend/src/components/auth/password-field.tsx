import { Eye, EyeOff, LockKeyhole } from "lucide-react";
import { useState } from "react";

import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group";

export function PasswordField({
  id,
  label,
  value,
  placeholder,
  autoComplete,
  error,
  showPasswordLabel,
  hidePasswordLabel,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  placeholder: string;
  autoComplete: string;
  error?: string;
  showPasswordLabel: string;
  hidePasswordLabel: string;
  onChange: (value: string) => void;
}) {
  const [showPassword, setShowPassword] = useState(false);
  const errorId = `${id}-error`;

  return (
    <Field data-invalid={Boolean(error)} className="gap-2">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <InputGroup>
        <InputGroupAddon>
          <LockKeyhole />
        </InputGroupAddon>
        <InputGroupInput
          id={id}
          autoComplete={autoComplete}
          type={showPassword ? "text" : "password"}
          aria-describedby={error ? errorId : undefined}
          aria-invalid={Boolean(error)}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
        />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            size="icon-xs"
            aria-label={showPassword ? hidePasswordLabel : showPasswordLabel}
            title={showPassword ? hidePasswordLabel : showPasswordLabel}
            onClick={() => setShowPassword((current) => !current)}
          >
            {showPassword ? <EyeOff /> : <Eye />}
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
      <FieldError id={errorId}>{error}</FieldError>
    </Field>
  );
}
