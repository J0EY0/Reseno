import type { LucideIcon } from "lucide-react";
import { useId, type ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

import { readonlyDisabledControlClassName } from "./editor-values";

export function TemplateTabLabel({
  icon: Icon,
  children,
}: {
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex max-w-full min-w-0 items-center justify-center gap-1.5">
      <Icon className="max-sm:hidden" />
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}

export function TemplateSelectRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4">
      <span className="flex min-w-0 items-center">
        <span className="min-w-0 text-sm leading-5 font-medium text-foreground">
          {label}
        </span>
      </span>
      {children}
    </label>
  );
}

export function TemplateSliderField({
  label,
  min,
  max,
  step,
  value,
  displayValue,
  onChange,
  disabled = false,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  displayValue: string;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className={cn(
        "grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4 py-2",
        disabled && "cursor-not-allowed text-muted-foreground",
      )}
    >
      <div className="min-w-0">
        <span className="text-sm font-medium">{label}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {displayValue}
        </span>
      </div>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={(next) => onChange(next[0] ?? value)}
        disabled={disabled}
        className={disabled ? "cursor-not-allowed" : undefined}
        thumbProps={{
          "aria-label": label,
        }}
      />
    </div>
  );
}

export function TemplateColorField({
  label,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const controlId = useId();

  return (
    <div
      className={cn(
        "grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4 py-2",
        disabled && "cursor-not-allowed text-muted-foreground",
      )}
    >
      <div className="min-w-0">
        <label htmlFor={controlId} className="block text-sm font-medium">
          {label}
        </label>
        <span className="rounded-md border border-border/70 bg-background px-2 py-1 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          {value}
        </span>
      </div>
      <div className="flex min-w-0 items-center gap-3">
        <Input
          id={controlId}
          type="color"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            "h-10 w-14 shrink-0 cursor-pointer rounded-lg border border-border/70 bg-background p-1",
            disabled && readonlyDisabledControlClassName,
          )}
          disabled={disabled}
        />
        <div
          className="h-10 flex-1 rounded-lg border border-border/70 bg-background"
          style={{ backgroundColor: value }}
        />
      </div>
    </div>
  );
}
