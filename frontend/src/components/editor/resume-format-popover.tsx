import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { AppMessages } from "@/i18n";
import {
  getResumeFontSizeInPoints,
  resumeFontSizeOptions,
} from "@/lib/templates";
import { cn } from "@/lib/utils";
import type {
  ResumeFontFamily,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeTemplateSettings,
  ResumeTypographySettings,
} from "@/types/resume";

const fontLabels: Record<
  ResumeFontFamily,
  "fontInter" | "fontNotoSans" | "fontSerif" | "fontPlex"
> = {
  inter: "fontInter",
  noto_sans_sc: "fontNotoSans",
  serif: "fontSerif",
  plex: "fontPlex",
};

function formatControlNumber(value: number, precision: number) {
  const formattedValue = value.toFixed(precision);

  return formattedValue.includes(".")
    ? formattedValue.replace(/\.?0+$/, "")
    : formattedValue;
}

function FormatSliderField({
  label,
  value,
  min,
  max,
  step,
  suffix,
  displayMultiplier = 1,
  displayPrecision,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  displayMultiplier?: number;
  displayPrecision?: number;
  onChange: (value: number) => void;
}) {
  const valuePrecision = step < 1 ? 2 : 0;
  const presentationPrecision = displayPrecision ?? valuePrecision;
  // The slider owns the canonical value. Unit conversion is presentation-only
  // so committing the text field cannot accumulate conversion drift.
  const formatDisplayValue = (nextValue: number) =>
    formatControlNumber(nextValue * displayMultiplier, presentationPrecision);
  const [inputValue, setInputValue] = useState(() =>
    formatControlNumber(value * displayMultiplier, presentationPrecision),
  );

  useEffect(() => {
    setInputValue(
      formatControlNumber(value * displayMultiplier, presentationPrecision),
    );
  }, [displayMultiplier, presentationPrecision, value]);

  function commitInputValue(nextInputValue: string) {
    if (!nextInputValue.trim()) {
      setInputValue(formatDisplayValue(value));
      return;
    }

    const parsedValue = Number(nextInputValue) / displayMultiplier;

    if (!Number.isFinite(parsedValue)) {
      setInputValue(formatDisplayValue(value));
      return;
    }

    const clampedValue = Math.min(max, Math.max(min, parsedValue));
    const steppedValue = Math.round((clampedValue - min) / step) * step + min;
    const nextValue = Number(
      Math.min(max, Math.max(min, steppedValue)).toFixed(valuePrecision),
    );

    setInputValue(formatDisplayValue(nextValue));
    onChange(nextValue);
  }

  return (
    <div className="grid gap-2 py-1">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <div className="flex items-center gap-0.5">
          <Input
            aria-label={label}
            inputMode="decimal"
            value={inputValue}
            className="h-7 w-14 rounded-md border-0 bg-muted/60 px-1.5 py-0 text-center text-sm tabular-nums text-muted-foreground shadow-none focus-visible:border-transparent focus-visible:ring-1"
            onBlur={(event) => commitInputValue(event.currentTarget.value)}
            onChange={(event) => {
              const nextValue = event.currentTarget.value;

              if (/^\d*\.?\d*$/.test(nextValue)) {
                setInputValue(nextValue);
              }
            }}
            onFocus={(event) => event.currentTarget.select()}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitInputValue(event.currentTarget.value);
                event.currentTarget.blur();
              }

              if (event.key === "Escape") {
                event.preventDefault();
                setInputValue(formatDisplayValue(value));
                event.currentTarget.blur();
              }
            }}
          />
          {suffix ? (
            <span className="text-sm tabular-nums text-muted-foreground">
              {suffix}
            </span>
          ) : null}
        </div>
      </div>
      <Slider
        className="[&_[data-slot=slider-thumb]]:size-3.5 [&_[data-slot=slider-track]]:h-1.5 [&_[data-slot=slider-track]]:bg-muted/70"
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={([nextValue]) => {
          if (typeof nextValue === "number") {
            onChange(nextValue);
          }
        }}
      />
    </div>
  );
}

export function ResumeFormatPopover({
  t,
  template,
  templates,
  typography,
  settings,
  hasTemplateStyleOverrides,
  onRestoreTemplateDefaults,
  onTemplateChange,
  onTypographyChange,
  onTemplateSettingsChange,
}: {
  t: AppMessages;
  template: ResumeTemplateId;
  templates: ResumeTemplateDefinition[];
  typography: ResumeTypographySettings;
  settings: ResumeTemplateSettings;
  hasTemplateStyleOverrides: boolean;
  onRestoreTemplateDefaults: () => void;
  onTemplateChange: (templateId: string) => void;
  onTypographyChange: (typography: ResumeTypographySettings) => void;
  onTemplateSettingsChange: (patch: Partial<ResumeTemplateSettings>) => void;
}) {
  return (
    <Popover>
      <PopoverTrigger
        type="button"
        className={cn(buttonVariants({ variant: "outline" }))}
      >
        <SlidersHorizontal className="size-4" />
        {t.format}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[340px] p-3">
        <div className="grid gap-2.5">
          <div className="flex min-h-8 items-center justify-between gap-3">
            <span className="text-sm font-medium text-foreground">
              {t.template}
            </span>
            <div className="flex min-w-0 items-center gap-1">
              <TooltipProvider delayDuration={180}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span
                      className="inline-flex"
                      tabIndex={hasTemplateStyleOverrides ? undefined : 0}
                      aria-label={
                        hasTemplateStyleOverrides
                          ? undefined
                          : t.templateDefaultsActive
                      }
                    >
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t.restoreTemplateDefaults}
                        disabled={!hasTemplateStyleOverrides}
                        onClick={onRestoreTemplateDefaults}
                      >
                        <RotateCcw data-icon="inline-start" />
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    {hasTemplateStyleOverrides
                      ? t.restoreTemplateDefaults
                      : t.templateDefaultsActive}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              <Select value={template} onValueChange={onTemplateChange}>
                <SelectTrigger
                  aria-label={t.applyTemplate}
                  className="h-8 min-w-[104px] max-w-[132px] justify-end rounded-md border-0 bg-transparent px-1.5 text-sm font-medium text-foreground shadow-none hover:bg-muted/60 focus-visible:border-transparent"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end" position="popper" sideOffset={6}>
                  <SelectGroup>
                    {templates.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          </div>

          <Separator />

          <div className="grid gap-1">
            <div className="flex min-h-8 items-center justify-between gap-3">
              <span className="text-sm font-medium text-foreground">
                {t.fontFamily}
              </span>
              <Select
                value={typography.fontFamily}
                onValueChange={(value) =>
                  onTypographyChange({
                    ...typography,
                    fontFamily: value as ResumeFontFamily,
                  })
                }
              >
                <SelectTrigger
                  aria-label={t.fontFamily}
                  className="h-8 w-[128px] justify-end rounded-md border-0 bg-transparent px-1.5 text-sm font-medium text-foreground shadow-none hover:bg-muted/60 focus-visible:border-transparent"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {Object.entries(fontLabels).map(([value, labelKey]) => (
                      <SelectItem key={value} value={value}>
                        {t[labelKey]}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>

            <div className="flex min-h-8 items-center justify-between gap-3">
              <span className="text-sm font-medium text-foreground">
                {t.fontSize}
              </span>
              <Select
                value={String(typography.fontSize)}
                onValueChange={(value) =>
                  onTypographyChange({
                    ...typography,
                    fontSize: Number(value),
                  })
                }
              >
                <SelectTrigger
                  aria-label={t.fontSize}
                  className="h-8 w-[104px] justify-end rounded-md border-0 bg-transparent px-1.5 text-sm font-medium text-foreground shadow-none hover:bg-muted/60 focus-visible:border-transparent"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {resumeFontSizeOptions.map((size) => (
                    <SelectItem key={size} value={String(size)}>
                      {getResumeFontSizeInPoints(size)} pt
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <Separator />

          <FormatSliderField
            label={t.pageMargin}
            value={settings.pagePaddingX}
            min={8}
            max={18}
            step={1}
            suffix="mm"
            onChange={(value) =>
              onTemplateSettingsChange({
                pagePaddingTop: value,
                pagePaddingX: value,
                pagePaddingBottom: value,
              })
            }
          />
          <FormatSliderField
            label={t.lineSpacing}
            value={settings.bodyLineHeight}
            min={1.4}
            max={2.2}
            step={0.05}
            suffix="pt"
            displayMultiplier={getResumeFontSizeInPoints(typography.fontSize)}
            displayPrecision={1}
            onChange={(value) =>
              onTemplateSettingsChange({ bodyLineHeight: value })
            }
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}
