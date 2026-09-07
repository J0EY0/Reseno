import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export function SettingsRow({
  icon,
  label,
  description,
  children,
}: {
  icon: ReactNode;
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="grid min-h-20 grid-cols-1 gap-4 px-5 py-4 sm:min-h-16 sm:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)] sm:items-center sm:gap-6 sm:px-6 sm:py-3"
    >
      <div className="flex min-w-0 items-start gap-3">
        <span
          className="mt-0.5 flex size-8 shrink-0 items-center justify-center text-foreground [&_svg]:size-5"
          aria-hidden="true"
        >
          {icon}
        </span>
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm font-medium text-foreground">{label}</div>
          {description ? (
            <p className="text-sm leading-5 text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
      </div>
      <div className="min-w-0 w-full sm:justify-self-end">{children}</div>
    </div>
  );
}

export function SettingsSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="grid gap-3">
      <h2 className="px-1 text-base font-semibold text-foreground">{title}</h2>
      <Card className="gap-0 overflow-hidden py-0">
        {children}
      </Card>
    </section>
  );
}

export function OptionSelect<T extends string>({
  className,
  label,
  items,
  value,
  onChange,
}: {
  className?: string;
  label: string;
  items: Array<{ value: T; label: string; icon?: ReactNode }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <Select
      value={value}
      onValueChange={(nextValue) => {
        const item = items.find((option) => option.value === nextValue);
        if (item) {
          onChange(item.value);
        }
      }}
    >
      <SelectTrigger
        aria-label={label}
        className={cn("ml-auto w-44 max-w-full", className)}
      >
        <SelectValue>{items.find((item) => item.value === value)?.label}</SelectValue>
      </SelectTrigger>
      <SelectContent align="end" position="popper" sideOffset={4}>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.icon}
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
