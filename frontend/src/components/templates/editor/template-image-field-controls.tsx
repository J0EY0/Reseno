import { FileUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
  FieldTitle,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type {
  ResumeTemplateImageElement,
  ResumeTemplateImageFit,
} from "@/types/resume";

import { readonlyDisabledControlClassName } from "./editor-values";
import {
  TemplateImageColorField,
  TemplateImageNumberField,
  TemplateImageSliderField,
} from "./image-fields";

type TemplateImageFieldProps = {
  t: AppMessages;
  image: ResumeTemplateImageElement;
  fileInputId: string;
  isReadonly: boolean;
  onUpdate: (patch: Partial<ResumeTemplateImageElement>) => void;
  onUpload: (file: File | undefined) => void;
};

function TemplateImageSourceFields({
  t,
  image,
  fileInputId,
  isReadonly,
  onUpdate,
  onUpload,
}: TemplateImageFieldProps) {
  const imageFitInputId = `${fileInputId}-fit`;

  return (
    <div className="grid gap-3">
      <Field
        orientation="horizontal"
        role="group"
        aria-label={t.imageSourceLabel}
        className="min-w-0 gap-3"
      >
        <FieldTitle className="shrink-0 text-xs">
          {t.imageSourceLabel}
        </FieldTitle>
        <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1">
          <Input
            id={fileInputId}
            type="file"
            accept="image/*"
            className="hidden"
            disabled={isReadonly}
            onChange={(event) => {
              onUpload(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => document.getElementById(fileInputId)?.click()}
            className={cn(
              "justify-center bg-background",
              readonlyDisabledControlClassName,
            )}
            disabled={isReadonly}
          >
            <FileUp data-icon="inline-start" />
            {image.src ? t.replaceImage : t.uploadImage}
          </Button>
        </div>
      </Field>
      <Field orientation="horizontal" className="min-w-0 gap-3">
        <FieldLabel htmlFor={imageFitInputId} className="shrink-0 text-xs">
          {t.imageFitLabel}
        </FieldLabel>
        <Select
          value={image.objectFit}
          disabled={isReadonly}
          onValueChange={(value) =>
            onUpdate({ objectFit: value as ResumeTemplateImageFit })
          }
        >
          <SelectTrigger
            id={imageFitInputId}
            size="sm"
            className="ml-auto w-40 max-w-full"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end" position="popper" sideOffset={4}>
            <SelectGroup>
              <SelectItem value="contain">{t.imageFitContain}</SelectItem>
              <SelectItem value="cover">{t.imageFitCover}</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>
    </div>
  );
}

function TemplateImageGeometryFields({
  t,
  image,
  fileInputId,
  isReadonly,
  onUpdate,
}: TemplateImageFieldProps) {
  const positionXMax = Math.max(0, 210 - image.width);
  const positionYMax = Math.max(0, 297 - image.height);
  const widthMax = Math.max(6, Math.min(120, 210 - image.x));
  const heightMax = Math.max(6, Math.min(120, 297 - image.y));

  return (
    <FieldSet className="gap-3">
      <FieldLegend variant="label" className="mb-0">
        {t.imagePositionAndSize}
      </FieldLegend>
      <FieldGroup className="gap-3">
        <FieldGroup className="grid grid-cols-1 gap-3 @min-[360px]/image-card:grid-cols-2">
          <TemplateImageNumberField
            id={`${fileInputId}-x`}
            label={t.imagePositionX}
            orientation="horizontal"
            min={0}
            max={positionXMax}
            step={0.5}
            value={image.x}
            unit="mm"
            onChange={(value) => onUpdate({ x: value })}
            disabled={isReadonly}
          />
          <TemplateImageNumberField
            id={`${fileInputId}-y`}
            label={t.imagePositionY}
            orientation="horizontal"
            min={0}
            max={positionYMax}
            step={0.5}
            value={image.y}
            unit="mm"
            onChange={(value) => onUpdate({ y: value })}
            disabled={isReadonly}
          />
        </FieldGroup>
        <FieldGroup className="grid grid-cols-1 gap-3 @min-[360px]/image-card:grid-cols-2">
          <TemplateImageNumberField
            id={`${fileInputId}-width`}
            label={t.imageWidth}
            orientation="horizontal"
            min={6}
            max={widthMax}
            step={0.5}
            value={image.width}
            unit="mm"
            onChange={(value) => onUpdate({ width: value })}
            disabled={isReadonly}
          />
          <TemplateImageNumberField
            id={`${fileInputId}-height`}
            label={t.imageHeight}
            orientation="horizontal"
            min={6}
            max={heightMax}
            step={0.5}
            value={image.height}
            unit="mm"
            onChange={(value) => onUpdate({ height: value })}
            disabled={isReadonly}
          />
        </FieldGroup>
      </FieldGroup>
    </FieldSet>
  );
}

function TemplateImageAppearanceFields({
  t,
  image,
  fileInputId,
  isReadonly,
  onUpdate,
}: TemplateImageFieldProps) {
  const hasImageBorder = image.borderWidth > 0;

  return (
    <FieldSet className="gap-3">
      <FieldLegend variant="label" className="mb-0">
        {t.imageAppearance}
      </FieldLegend>
      <FieldGroup className="gap-3">
        <TemplateImageSliderField
          id={`${fileInputId}-opacity`}
          label={t.imageOpacity}
          min={0.05}
          max={1}
          step={0.05}
          value={image.opacity}
          onChange={(value) => onUpdate({ opacity: value })}
          disabled={isReadonly}
        />
        <FieldGroup className="grid grid-cols-1 gap-3 @min-[360px]/image-card:grid-cols-2">
          <TemplateImageNumberField
            id={`${fileInputId}-border-radius`}
            label={t.imageBorderRadius}
            orientation="horizontal"
            min={0}
            max={32}
            step={1}
            value={image.borderRadius}
            unit="px"
            onChange={(value) => onUpdate({ borderRadius: value })}
            disabled={isReadonly}
          />
          {hasImageBorder ? (
            <TemplateImageNumberField
              id={`${fileInputId}-border-width`}
              label={t.imageBorderWidth}
              orientation="horizontal"
              min={0.5}
              max={8}
              step={0.5}
              value={image.borderWidth}
              unit="px"
              onChange={(value) => onUpdate({ borderWidth: value })}
              disabled={isReadonly}
            />
          ) : null}
        </FieldGroup>
        <FieldGroup className="grid grid-cols-1 gap-3 @min-[360px]/image-card:grid-cols-2">
          <Field orientation="horizontal">
            <FieldTitle className="text-xs">{t.imageBorder}</FieldTitle>
            <Button
              type="button"
              role="switch"
              variant="ghost"
              size="sm"
              data-state={hasImageBorder ? "checked" : "unchecked"}
              aria-label={t.imageBorder}
              aria-checked={hasImageBorder}
              className={cn(
                "group ml-auto h-6 w-11 justify-start rounded-full p-0 shadow-none transition-colors",
                hasImageBorder
                  ? "bg-primary hover:bg-primary/90"
                  : "bg-muted-foreground/30 hover:bg-muted-foreground/40",
              )}
              onClick={() =>
                onUpdate({ borderWidth: hasImageBorder ? 0 : 1 })
              }
              disabled={isReadonly}
            >
              <span
                aria-hidden="true"
                className="ml-0.5 size-5 rounded-full bg-background shadow-xs transition-transform group-data-[state=checked]:translate-x-5"
              />
            </Button>
          </Field>
          {hasImageBorder ? (
            <TemplateImageColorField
              id={`${fileInputId}-border-color`}
              label={t.imageBorderColor}
              value={image.borderColor}
              onChange={(value) => onUpdate({ borderColor: value })}
              disabled={isReadonly}
            />
          ) : null}
        </FieldGroup>
      </FieldGroup>
    </FieldSet>
  );
}

export function TemplateImageFieldControls(props: TemplateImageFieldProps) {
  return (
    <FieldGroup
      data-slot="template-image-card-content"
      className="collapsible-content-inner gap-5 p-3"
    >
      <TemplateImageSourceFields {...props} />
      <TemplateImageGeometryFields {...props} />
      <TemplateImageAppearanceFields {...props} />
    </FieldGroup>
  );
}
