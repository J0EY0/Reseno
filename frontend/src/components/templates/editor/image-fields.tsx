import { useState } from "react";

import {
  Field,
  FieldLabel,
} from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

import { readonlyDisabledControlClassName } from "./editor-values";

function clampTemplateImageValue(
  value: number,
  min: number,
  max: number,
  step: number,
) {
  const clamped = Math.min(Math.max(value, min), max);
  const stepped = min + Math.round((clamped - min) / step) * step;

  return Number(Math.min(Math.max(stepped, min), max).toFixed(4));
}

function formatTemplateImageValue(value: number) {
  return String(Number(value.toFixed(4)));
}

export function TemplateImageNumberField({
  id,
  label,
  orientation = "vertical",
  min,
  max,
  step,
  value,
  unit,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  orientation?: "vertical" | "horizontal";
  min: number;
  max: number;
  step: number;
  value: number;
  unit: string;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const unitId = `${id}-unit`;
  const inputValue = draft ?? formatTemplateImageValue(value);
  const parsedDraft = Number(inputValue);
  const isDraftValid =
    inputValue.trim() !== "" &&
    Number.isFinite(parsedDraft) &&
    parsedDraft >= min &&
    parsedDraft <= max;

  function updateDraft(nextDraft: string) {
    setDraft(nextDraft);
    const parsed = Number(nextDraft);

    // Keep the preview and autosave state current while preserving the
    // user's temporary input string until the field is committed.
    if (nextDraft.trim() !== "" && Number.isFinite(parsed)) {
      onChange(clampTemplateImageValue(parsed, min, max, step));
    }
  }

  function commitDraft() {
    const currentDraft = draft ?? formatTemplateImageValue(value);
    const parsed = Number(currentDraft);
    const nextValue =
      currentDraft.trim() !== "" && Number.isFinite(parsed)
        ? clampTemplateImageValue(parsed, min, max, step)
        : value;

    onChange(nextValue);
    setDraft(null);
  }

  return (
    <Field
      orientation={orientation}
      className={cn(
        "gap-1.5",
        orientation === "horizontal" && "min-w-0 gap-2",
      )}
      data-disabled={disabled || undefined}
    >
      <FieldLabel
        htmlFor={id}
        className={cn(
          "text-xs",
          orientation === "horizontal"
            ? "min-w-0 leading-tight"
            : "whitespace-nowrap",
        )}
      >
        {label}
      </FieldLabel>
      <InputGroup
        className={orientation === "horizontal" ? "w-28 shrink-0" : undefined}
        data-disabled={disabled || undefined}
      >
        <InputGroupInput
          id={id}
          type="number"
          inputMode="decimal"
          min={min}
          max={max}
          step={step}
          value={inputValue}
          onFocus={() => setDraft(formatTemplateImageValue(value))}
          onChange={(event) => updateDraft(event.target.value)}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }

            if (event.key === "Escape") {
              event.preventDefault();
              setDraft(null);
            }
          }}
          aria-describedby={unitId}
          aria-invalid={!isDraftValid || undefined}
          disabled={disabled}
          className="text-right tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-outer-spin-button]:appearance-none"
        />
        <InputGroupAddon align="inline-end">
          <InputGroupText id={unitId} translate="no">
            {unit}
          </InputGroupText>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  );
}

export function TemplateImageSliderField({
  id,
  label,
  min,
  max,
  step,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const unitId = `${id}-unit`;
  const minPercent = min * 100;
  const maxPercent = max * 100;
  const stepPercent = step * 100;
  const percentValue = Math.round(value * 100);
  const inputValue = draft ?? String(percentValue);
  const parsedDraft = Number(inputValue);
  const isDraftValid =
    inputValue.trim() !== "" &&
    Number.isFinite(parsedDraft) &&
    parsedDraft >= minPercent &&
    parsedDraft <= maxPercent;
  const displayValue = `${percentValue}%`;

  function updateDraft(nextDraft: string) {
    setDraft(nextDraft);
    const parsed = Number(nextDraft);

    if (nextDraft.trim() !== "" && Number.isFinite(parsed)) {
      onChange(
        clampTemplateImageValue(
          parsed,
          minPercent,
          maxPercent,
          stepPercent,
        ) / 100,
      );
    }
  }

  function commitDraft() {
    const currentDraft = draft ?? String(percentValue);
    const parsed = Number(currentDraft);
    const nextPercent =
      currentDraft.trim() !== "" && Number.isFinite(parsed)
        ? clampTemplateImageValue(
            parsed,
            minPercent,
            maxPercent,
            stepPercent,
          )
        : percentValue;

    onChange(nextPercent / 100);
    setDraft(null);
  }

  return (
    <Field
      orientation="horizontal"
      data-slot="template-image-slider-field"
      className="grid grid-cols-[5.5rem_minmax(0,1fr)_7rem] items-center gap-3"
      data-disabled={disabled || undefined}
    >
      <FieldLabel htmlFor={id} className="w-auto text-xs">
        {label}
      </FieldLabel>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={(next) => {
          setDraft(null);
          onChange(next[0] ?? value);
        }}
        disabled={disabled}
        thumbProps={{
          "aria-label": label,
          "aria-valuetext": displayValue,
        }}
        className={cn("min-w-0", disabled && "cursor-not-allowed")}
      />
      <InputGroup
        data-template-image-slider-value="true"
        className="w-28 shrink-0"
        data-disabled={disabled || undefined}
      >
        <InputGroupInput
          id={id}
          type="number"
          inputMode="decimal"
          min={minPercent}
          max={maxPercent}
          step={stepPercent}
          value={inputValue}
          onFocus={() => setDraft(String(percentValue))}
          onChange={(event) => updateDraft(event.target.value)}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }

            if (event.key === "Escape") {
              event.preventDefault();
              setDraft(null);
            }
          }}
          aria-describedby={unitId}
          aria-invalid={!isDraftValid || undefined}
          disabled={disabled}
          className="text-right tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-outer-spin-button]:appearance-none"
        />
        <InputGroupAddon align="inline-end">
          <InputGroupText id={unitId} translate="no">
            %
          </InputGroupText>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  );
}

export function TemplateImageColorField({
  id,
  label,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <Field
      orientation="horizontal"
      className="min-w-0 gap-2"
      data-disabled={disabled || undefined}
    >
      <FieldLabel htmlFor={id} className="min-w-0 text-xs leading-tight">
        {label}
      </FieldLabel>
      <InputGroup
        className="w-28 shrink-0"
        data-disabled={disabled || undefined}
      >
        <InputGroupInput
          id={id}
          type="color"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          className={cn(
            "m-1 size-7 flex-none cursor-pointer rounded-sm p-0",
            disabled && readonlyDisabledControlClassName,
          )}
        />
        <InputGroupAddon align="inline-end" className="min-w-0 pl-1 pr-2">
          <InputGroupText className="truncate font-mono text-[10px] uppercase tracking-[0.04em]">
            {value}
          </InputGroupText>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  );
}
