import type { ReactNode } from "react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group";

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
      className="grid min-h-20 gap-4 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)] sm:items-center sm:gap-6 sm:px-6"
    >
      <div className="flex min-w-0 items-start gap-3">
        <span
          className="mt-0.5 flex size-8 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-5"
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
      <div className="w-full sm:justify-self-end">{children}</div>
    </div>
  );
}

export function SettingsSection({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <Card className="gap-0 overflow-hidden rounded-xl py-0 shadow-xs">
      <CardHeader className="px-5 py-4 sm:px-6 sm:py-5">
        <CardTitle
          role="heading"
          aria-level={2}
          className="flex items-center gap-2.5 text-base"
        >
          <span
            className="flex size-7 items-center justify-center text-muted-foreground [&_svg]:size-[18px]"
            aria-hidden="true"
          >
            {icon}
          </span>
          {title}
        </CardTitle>
      </CardHeader>
      <Separator />
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  );
}

export function OptionToggleGroup<T extends string>({
  items,
  value,
  onChange,
}: {
  items: Array<{ value: T; label: string; icon?: ReactNode }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      spacing={0}
      value={value}
      className="w-full"
      onValueChange={(nextValue) => {
        if (nextValue) {
          onChange(nextValue as T);
        }
      }}
    >
      {items.map((item) => (
        <ToggleGroupItem
          key={item.value}
          value={item.value}
          aria-label={item.label}
          className="min-w-0 flex-auto shrink px-2 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
        >
          {item.icon}
          <span className="min-w-0 truncate">{item.label}</span>
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
