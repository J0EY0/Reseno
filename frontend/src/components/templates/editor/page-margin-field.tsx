import { ChevronDown } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { ResumeTemplateSettings } from "@/types/resume";

import { TemplateNumberInput, TemplateSliderField } from "./editor-fields";
import type { TemplateEditorMessages } from "./editor-messages";

export function TemplatePageMarginField({
  t,
  settings,
  disabled,
  onChange,
}: {
  t: TemplateEditorMessages;
  settings: ResumeTemplateSettings;
  disabled: boolean;
  onChange: (patch: Partial<ResumeTemplateSettings>) => void;
}) {
  const id = useId();
  const hasMixedMargins =
    settings.pagePaddingTop !== settings.pagePaddingX ||
    settings.pagePaddingBottom !== settings.pagePaddingX;

  function setUniformMargin(value: number) {
    if (!disabled)
      onChange({
        pagePaddingTop: value,
        pagePaddingX: value,
        pagePaddingBottom: value,
      });
  }

  return (
    <TemplateSliderField
      label={t.pageMargin}
      min={8}
      max={18}
      step={1}
      value={settings.pagePaddingX}
      mixedValueLabel={hasMixedMargins ? t.templateCustomValue : undefined}
      unit="mm"
      disabled={disabled}
      onChange={setUniformMargin}
      valueControl={
        <Popover>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="outline"
              aria-label={t.pageMarginDetails}
              className="template-control w-full gap-1 px-2 font-normal tabular-nums has-[>svg]:px-2"
            >
              {hasMixedMargins
                ? t.templateCustomValue
                : `${settings.pagePaddingX} mm`}
              <ChevronDown
                aria-hidden="true"
                className="text-muted-foreground"
              />
            </Button>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            collisionPadding={12}
            aria-label={t.pageMargin}
            className="flex w-64 max-w-[calc(100vw-1.5rem)] flex-col gap-4 motion-reduce:animate-none"
          >
            <h3 className="text-sm font-medium">{t.pageMargin}</h3>
            <FieldGroup className="gap-2">
              {(
                [
                  ["pagePaddingTop", t.pageMarginTop, 20],
                  ["pagePaddingX", t.pageMarginHorizontal, 18],
                  ["pagePaddingBottom", t.pageMarginBottom, 18],
                ] as const
              ).map(([key, label, max]) => (
                <Field
                  key={key}
                  orientation="horizontal"
                  className="grid grid-cols-[minmax(0,1fr)_88px] items-center gap-3"
                >
                  <FieldLabel
                    htmlFor={`${id}-${key}`}
                    className="font-normal text-muted-foreground"
                  >
                    {label}
                  </FieldLabel>
                  <TemplateNumberInput
                    id={`${id}-${key}`}
                    label={label}
                    min={8}
                    max={max}
                    step={1}
                    unit="mm"
                    value={settings[key]}
                    disabled={disabled}
                    onChange={(value) => {
                      if (!disabled) onChange({ [key]: value });
                    }}
                  />
                </Field>
              ))}
            </FieldGroup>
            {disabled ? null : (
              <div className="flex flex-col gap-2 border-t pt-3">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={!hasMixedMargins}
                  onClick={() => setUniformMargin(settings.pagePaddingX)}
                >
                  {t.pageMarginUnify}
                </Button>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {t.pageMarginHint}
                </p>
              </div>
            )}
          </PopoverContent>
        </Popover>
      }
    />
  );
}
