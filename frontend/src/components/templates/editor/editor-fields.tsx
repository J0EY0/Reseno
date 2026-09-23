import { useId, useState, type ReactNode } from "react";

import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";

export function TemplateControlSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <FieldSet className="template-control-section">
      <FieldLegend variant="label">{title}</FieldLegend>
      <FieldGroup>{children}</FieldGroup>
    </FieldSet>
  );
}

export function TemplateSelectField<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: {
    value: T;
    label: string;
    disabled?: boolean;
    preview?: ReactNode;
  }[];
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const selectedOption = options.find((option) => option.value === value);
  return (
    <Field
      orientation="horizontal"
      data-disabled={disabled}
      className="template-field-row"
    >
      <FieldLabel htmlFor={id} className="template-control-label">
        {label}
      </FieldLabel>
      <Select
        value={value}
        disabled={disabled}
        onValueChange={(next) => onChange(next as T)}
      >
        <SelectTrigger
          id={id}
          className="template-control w-full min-w-0"
          data-has-preview={Boolean(selectedOption?.preview) || undefined}
        >
          <SelectValue>
            {selectedOption?.preview ? (
              <>
                <span aria-hidden="true" className="template-select-preview">
                  {selectedOption.preview}
                </span>
                <span>{selectedOption.label}</span>
              </>
            ) : (
              selectedOption?.label
            )}
          </SelectValue>
        </SelectTrigger>
        <SelectContent
          align="end"
          position="popper"
          sideOffset={4}
          className="w-max max-w-[calc(100vw-2rem)]"
        >
          <SelectGroup>
            {options.map((option) => (
              <SelectItem
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                textValue={option.label}
              >
                {option.preview ? (
                  <span aria-hidden="true" className="shrink-0">
                    {option.preview}
                  </span>
                ) : null}
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  );
}

export function TemplateNumberInput({
  id,
  label,
  value,
  min,
  max,
  step,
  unit,
  displayPrecision = 2,
  onChange,
  disabled = false,
}: {
  id?: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  displayPrecision?: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  function updateValue(parsed: number) {
    if (disabled || !Number.isFinite(parsed)) return;
    const next = Number(
      Math.min(max, Math.max(min, Math.round(parsed / step) * step)).toFixed(2),
    );
    if (next !== value) onChange(next);
  }
  function commit() {
    if (draft !== null && draft.trim() !== "") updateValue(Number(draft));
    setDraft(null);
  }
  return (
    <InputGroup className="template-control" data-disabled={disabled}>
      <InputGroupInput
        id={id}
        type="number"
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={draft ?? Number(value.toFixed(displayPrecision))}
        disabled={disabled}
        className="min-w-0 px-2 text-right tabular-nums disabled:opacity-100 [appearance:textfield] [&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-outer-spin-button]:appearance-none"
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          const parsed = Number(next);
          if (next.trim() !== "" && parsed >= min && parsed <= max)
            updateValue(parsed);
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
          if (event.key === "Escape") {
            event.preventDefault();
            setDraft(null);
          }
        }}
      />
      <InputGroupAddon
        align="inline-end"
        className="pr-2 group-data-[disabled=true]/input-group:opacity-100"
      >
        <InputGroupText className="text-xs">{unit}</InputGroupText>
      </InputGroupAddon>
    </InputGroup>
  );
}

export function TemplateSliderField({
  label,
  min,
  max,
  step,
  value,
  unit,
  mixedValueLabel,
  valueControl,
  displayScale = 1,
  displayPrecision = 2,
  onChange,
  disabled = false,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  unit: string;
  mixedValueLabel?: string;
  valueControl?: ReactNode;
  displayScale?: number;
  displayPrecision?: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  return (
    <Field
      orientation="horizontal"
      data-disabled={disabled}
      className="template-field-row"
    >
      <span id={labelId} className="template-control-label">
        {label}
      </span>
      <div className="template-slider-control">
        <Slider
          min={min}
          max={max}
          step={step}
          value={[value]}
          onValueChange={(next) => {
            if (!disabled) onChange(next[0] ?? value);
          }}
          disabled={disabled}
          thumbProps={{
            "aria-labelledby": labelId,
            "aria-valuetext":
              mixedValueLabel ??
              `${Number((value * displayScale).toFixed(displayPrecision))} ${unit}`,
          }}
        />
        {valueControl ?? (
          <TemplateNumberInput
            label={label}
            min={min * displayScale}
            max={max * displayScale}
            step={step * displayScale}
            value={value * displayScale}
            unit={unit}
            displayPrecision={displayPrecision}
            disabled={disabled}
            onChange={(next) =>
              onChange(Number((next / displayScale).toFixed(2)))
            }
          />
        )}
      </div>
    </Field>
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
  const [draft, setDraft] = useState<string | null>(null);
  function updateValue(candidate: string) {
    const normalized = candidate.trim().replace(/^#/, "");
    if (!disabled && /^[\da-f]{6}$/i.test(normalized)) {
      const next = `#${normalized.toLowerCase()}`;
      if (next !== value.toLowerCase()) onChange(next);
    }
  }
  function commit() {
    if (draft !== null) updateValue(draft);
    setDraft(null);
  }
  return (
    <Field data-disabled={disabled} className="min-w-0 gap-2">
      <FieldLabel htmlFor={controlId} className="template-control-label">
        {label}
      </FieldLabel>
      <InputGroup className="template-control" data-disabled={disabled}>
        <InputGroupAddon className="pl-1.5 group-data-[disabled=true]/input-group:opacity-100">
          <Input
            id={controlId}
            type="color"
            value={value}
            onChange={(event) => {
              setDraft(null);
              if (!disabled) onChange(event.target.value);
            }}
            disabled={disabled}
            className="size-5 shrink-0 cursor-pointer rounded border-0 p-0 disabled:opacity-100 [&::-moz-color-swatch]:border-0 [&::-webkit-color-swatch]:rounded [&::-webkit-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0"
          />
        </InputGroupAddon>
        <InputGroupInput
          aria-label={`${label} HEX`}
          value={draft ?? value.toUpperCase()}
          maxLength={7}
          spellCheck={false}
          autoComplete="off"
          disabled={disabled}
          className="min-w-0 px-2 font-mono uppercase disabled:opacity-100"
          onChange={(event) => {
            setDraft(event.target.value);
            updateValue(event.target.value);
          }}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setDraft(null);
            }
          }}
        />
      </InputGroup>
    </Field>
  );
}
