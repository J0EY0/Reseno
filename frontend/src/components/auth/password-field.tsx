import { Eye, EyeOff, LockKeyhole } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
    <div className="grid gap-2">
      <label htmlFor={id} className="text-sm font-medium text-foreground">
        {label}
      </label>
      <div className="relative">
        <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          id={id}
          autoComplete={autoComplete}
          type={showPassword ? "text" : "password"}
          aria-describedby={error ? errorId : undefined}
          aria-invalid={Boolean(error)}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="h-11 rounded-xl border-border bg-background pl-10 pr-11"
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute right-1 top-1/2 size-9 -translate-y-1/2 rounded-lg text-muted-foreground"
          aria-label={showPassword ? hidePasswordLabel : showPasswordLabel}
          title={showPassword ? hidePasswordLabel : showPasswordLabel}
          onClick={() => setShowPassword((current) => !current)}
        >
          {showPassword ? (
            <EyeOff className="size-4" />
          ) : (
            <Eye className="size-4" />
          )}
        </Button>
      </div>
      {error ? (
        <p id={errorId} className="text-xs text-red-600">
          {error}
        </p>
      ) : null}
    </div>
  );
}
