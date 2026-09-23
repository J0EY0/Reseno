import { useState } from "react";

import { Field, FieldLabel } from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

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

type ImageNumberInputProps = {
  id: string;
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  unit: string;
  prefix?: string;
  onChange: (value: number) => void;
  disabled?: boolean;
};

function ImageNumberInput({
  id,
  label,
  min,
  max,
  step,
  value,
  unit,
  prefix,
  onChange,
  disabled,
}: ImageNumberInputProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const inputValue = draft ?? formatTemplateImageValue(value);
  const parsedDraft = Number(inputValue);
  const isDraftValid =
    inputValue.trim() !== "" &&
    Number.isFinite(parsedDraft) &&
    parsedDraft >= min &&
    parsedDraft <= max;
  const unitId = `${id}-unit`;

  function commitDraft() {
    const nextValue =
      inputValue.trim() !== "" && Number.isFinite(parsedDraft)
        ? clampTemplateImageValue(parsedDraft, min, max, step)
        : value;
    if (nextValue !== value) onChange(nextValue);
    setDraft(null);
  }

  return (
    <InputGroup
      className="template-control"
      data-template-image-slider-value={prefix ? undefined : "true"}
      data-disabled={disabled || undefined}
    >
      {prefix ? (
        <InputGroupAddon className="pl-2">
          <FieldLabel htmlFor={id} className="text-xs font-normal">
            <span className="sr-only">{label}</span>
            <span aria-hidden="true">{prefix}</span>
          </FieldLabel>
        </InputGroupAddon>
      ) : null}
      <InputGroupInput
        id={id}
        aria-label={label}
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        value={inputValue}
        onFocus={() => setDraft(formatTemplateImageValue(value))}
        onChange={(event) => {
          const nextDraft = event.target.value;
          setDraft(nextDraft);
          const parsed = Number(nextDraft);
          if (nextDraft.trim() !== "" && Number.isFinite(parsed)) {
            const nextValue = clampTemplateImageValue(parsed, min, max, step);
            if (nextValue !== value) onChange(nextValue);
          }
        }}
        onBlur={commitDraft}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") {
            event.preventDefault();
            setDraft(null);
          }
        }}
        aria-describedby={unitId}
        aria-invalid={!isDraftValid || undefined}
        disabled={disabled}
        className="min-w-0 text-right tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-outer-spin-button]:appearance-none"
      />
      <InputGroupAddon align="inline-end" className="pl-0 pr-2">
        <InputGroupText id={unitId} translate="no" className="text-xs">
          {unit}
        </InputGroupText>
      </InputGroupAddon>
    </InputGroup>
  );
}

export function TemplateImageNumberField(props: ImageNumberInputProps) {
  return (
    <Field className="min-w-0" data-disabled={props.disabled || undefined}>
      <ImageNumberInput {...props} prefix={props.prefix ?? props.label} />
    </Field>
  );
}

export function TemplateImageSliderField({
  valueScale = 1,
  displayLabel,
  ...props
}: ImageNumberInputProps & { valueScale?: number; displayLabel?: string }) {
  const { id, label, min, max, step, value, unit, onChange, disabled } = props;
  const displayValue = formatTemplateImageValue(value * valueScale);
  return (
    <Field
      orientation="horizontal"
      data-slot="template-image-slider-field"
      className="template-image-slider-row"
      data-disabled={disabled || undefined}
    >
      <FieldLabel htmlFor={id} className="template-control-label">
        {displayLabel ?? label}
      </FieldLabel>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={(next) => onChange(next[0] ?? value)}
        disabled={disabled}
        thumbProps={{
          "aria-label": label,
          "aria-valuetext": `${displayValue}${unit}`,
        }}
        className={cn("min-w-0", disabled && "cursor-not-allowed")}
      />
      <ImageNumberInput
        {...props}
        min={min * valueScale}
        max={max * valueScale}
        step={step * valueScale}
        value={value * valueScale}
        onChange={(next) => onChange(next / valueScale)}
      />
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
  const [draft, setDraft] = useState<string | null>(null);
  const inputValue = draft ?? value.toUpperCase();
  const isValid = /^#[\da-f]{6}$/i.test(inputValue);

  return (
    <Field className="min-w-0" data-disabled={disabled || undefined}>
      <FieldLabel htmlFor={id} className="sr-only">
        {label}
      </FieldLabel>
      <InputGroup
        className="template-control"
        data-disabled={disabled || undefined}
      >
        <InputGroupAddon className="pl-2 pr-0">
          <InputGroupInput
            type="color"
            value={value}
            aria-label={`${label} ${value.toUpperCase()}`}
            onChange={(event) => {
              setDraft(null);
              onChange(event.target.value);
            }}
            disabled={disabled}
            className="size-5 flex-none cursor-pointer overflow-hidden rounded-sm p-0 [&::-webkit-color-swatch-wrapper]:p-0 [&::-webkit-color-swatch]:border-0"
          />
        </InputGroupAddon>
        <InputGroupInput
          id={id}
          value={inputValue}
          spellCheck={false}
          autoComplete="off"
          maxLength={7}
          onChange={(event) => {
            const next = event.target.value;
            setDraft(next);
            if (/^#[\da-f]{6}$/i.test(next)) onChange(next.toLowerCase());
          }}
          onBlur={() => setDraft(null)}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              event.preventDefault();
              setDraft(null);
            }
          }}
          aria-invalid={!isValid || undefined}
          disabled={disabled}
          className="min-w-0 px-2 font-mono uppercase"
        />
      </InputGroup>
    </Field>
  );
}
