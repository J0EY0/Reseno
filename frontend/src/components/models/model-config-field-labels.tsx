import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { FieldLabel } from "@/components/ui/field";

export function ModelFormFieldLabel({
  htmlFor,
  label,
  required = false,
}: {
  htmlFor?: string;
  label: string;
  required?: boolean;
}) {
  return (
    <FieldLabel htmlFor={htmlFor}>
      <span>{label}</span>
      {required ? <span className="text-destructive">*</span> : null}
    </FieldLabel>
  );
}

export function ProviderKindBadge({ children }: { children: ReactNode }) {
  return (
    <Badge
      variant="outline"
      className="h-4 px-1 py-0 text-[9px] font-normal text-muted-foreground"
    >
      {children}
    </Badge>
  );
}
