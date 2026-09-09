import { cloneElement, useId, type ReactElement } from "react";

import { Field, FieldLabel } from "@/components/ui/field";
import { cn } from "@/lib/utils";

export function FormField({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactElement<{ id?: string }>;
}) {
  const generatedId = useId();
  const controlId = children.props.id ?? generatedId;

  return (
    <Field className={cn("min-w-0 gap-2", className)}>
      <FieldLabel
        htmlFor={controlId}
        onClick={() => {
          const control = document.getElementById(controlId);
          if (control?.isContentEditable) control.focus();
        }}
        className="break-words text-xs font-medium leading-tight text-muted-foreground"
      >
        {label}
      </FieldLabel>
      {cloneElement(children, { id: controlId })}
    </Field>
  );
}
