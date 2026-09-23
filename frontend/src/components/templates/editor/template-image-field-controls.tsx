import { useState } from "react";

import {
  TemplateStyleTabs,
  TemplateStyleTabsContent,
  TemplateStyleTabsList,
  TemplateStyleTabsTrigger,
} from "@/components/templates/template-style-tabs";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import type { AppMessages } from "@/i18n";
import type { ResumeTemplateImageElement } from "@/types/resume";

import type { ImageEditorMessages } from "./image-messages";
import {
  TemplateImageColorField,
  TemplateImageNumberField,
  TemplateImageSliderField,
} from "./image-fields";

type TemplateImageFieldProps = {
  t: AppMessages;
  messages: ImageEditorMessages;
  image: ResumeTemplateImageElement;
  fileInputId: string;
  isReadonly: boolean;
  onUpdate: (patch: Partial<ResumeTemplateImageElement>) => void;
};

function TemplateImageGeometryFields({
  t,
  messages,
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
    <FieldSet className="min-w-0">
      <FieldLegend className="sr-only">{t.imagePositionAndSize}</FieldLegend>
      <FieldGroup className="gap-2.5">
        <Field orientation="horizontal" className="template-field-row">
          <span className="template-control-label">{messages.position}</span>
          <FieldGroup className="template-image-pair">
            <TemplateImageNumberField
              id={`${fileInputId}-x`}
              label={t.imagePositionX}
              prefix="X"
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
              prefix="Y"
              min={0}
              max={positionYMax}
              step={0.5}
              value={image.y}
              unit="mm"
              onChange={(value) => onUpdate({ y: value })}
              disabled={isReadonly}
            />
          </FieldGroup>
        </Field>
        <Field orientation="horizontal" className="template-field-row">
          <span className="template-control-label">{messages.size}</span>
          <FieldGroup className="template-image-pair">
            <TemplateImageNumberField
              id={`${fileInputId}-width`}
              label={t.imageWidth}
              prefix="W"
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
              prefix="H"
              min={6}
              max={heightMax}
              step={0.5}
              value={image.height}
              unit="mm"
              onChange={(value) => onUpdate({ height: value })}
              disabled={isReadonly}
            />
          </FieldGroup>
        </Field>
      </FieldGroup>
    </FieldSet>
  );
}

function TemplateImageAppearanceFields({
  t,
  messages,
  image,
  fileInputId,
  isReadonly,
  onUpdate,
}: TemplateImageFieldProps) {
  return (
    <FieldSet className="min-w-0">
      <FieldLegend className="sr-only">{t.imageAppearance}</FieldLegend>
      <FieldGroup className="gap-2.5">
        <TemplateImageSliderField
          id={`${fileInputId}-opacity`}
          label={t.imageOpacity}
          min={0.05}
          max={1}
          step={0.05}
          value={image.opacity}
          valueScale={100}
          unit="%"
          onChange={(value) => onUpdate({ opacity: value })}
          disabled={isReadonly}
        />
        <TemplateImageSliderField
          id={`${fileInputId}-border-radius`}
          label={t.imageBorderRadius}
          displayLabel={messages.radius}
          min={0}
          max={32}
          step={1}
          value={image.borderRadius}
          unit="px"
          onChange={(value) => onUpdate({ borderRadius: value })}
          disabled={isReadonly}
        />
      </FieldGroup>
    </FieldSet>
  );
}

function TemplateImageBorderFields({
  t,
  image,
  fileInputId,
  isReadonly,
  onUpdate,
}: TemplateImageFieldProps) {
  const hasImageBorder = image.borderWidth > 0;
  const borderId = `${fileInputId}-border`;
  const [visibleBorderWidth, setVisibleBorderWidth] = useState(
    image.borderWidth,
  );
  if (hasImageBorder && visibleBorderWidth !== image.borderWidth) {
    setVisibleBorderWidth(image.borderWidth);
  }

  return (
    <Collapsible open={hasImageBorder} asChild>
      <FieldSet className="min-w-0">
        <FieldLegend className="sr-only">{t.imageBorder}</FieldLegend>
        <FieldGroup className="template-field-row">
          <Field
            orientation="horizontal"
            className="template-image-border-toggle"
          >
            <FieldLabel htmlFor={borderId} className="template-control-label">
              {t.imageBorder}
            </FieldLabel>
            <Switch
              id={borderId}
              className="after:inset-x-0"
              aria-label={t.imageBorder}
              checked={hasImageBorder}
              onCheckedChange={(checked) =>
                onUpdate({ borderWidth: checked ? 1 : 0 })
              }
              disabled={isReadonly}
            />
          </Field>
          <CollapsibleContent asChild>
            <FieldGroup
              className="template-image-border-controls template-image-border-presence"
              inert={!hasImageBorder}
              aria-hidden={!hasImageBorder}
            >
              <TemplateImageColorField
                id={`${fileInputId}-border-color`}
                label={t.imageBorderColor}
                value={image.borderColor}
                onChange={(value) => onUpdate({ borderColor: value })}
                disabled={isReadonly || !hasImageBorder}
              />
              <TemplateImageNumberField
                id={`${fileInputId}-border-width`}
                label={t.imageBorderWidth}
                prefix=""
                min={0.5}
                max={8}
                step={0.5}
                value={visibleBorderWidth}
                unit="px"
                onChange={(value) => onUpdate({ borderWidth: value })}
                disabled={isReadonly || !hasImageBorder}
              />
            </FieldGroup>
          </CollapsibleContent>
        </FieldGroup>
      </FieldSet>
    </Collapsible>
  );
}

export function TemplateImageFieldControls(props: TemplateImageFieldProps) {
  const { t, image, isReadonly, onUpdate } = props;

  return (
    <TemplateStyleTabs
      data-slot="template-image-card-content"
      className="collapsible-content-inner template-control-stack template-image-properties min-w-0 py-3"
      value={image.objectFit}
      onValueChange={(value) => {
        if (!isReadonly && (value === "contain" || value === "cover")) {
          onUpdate({ objectFit: value });
        }
      }}
    >
      <Field orientation="horizontal" className="template-field-row">
        <span className="template-control-label">{t.imageFitLabel}</span>
        <TemplateStyleTabsList aria-label={t.imageFitLabel} size="sm">
          <TemplateStyleTabsTrigger
            value="contain"
            disabled={isReadonly}
            style={{ flex: 1 }}
          >
            {t.imageFitContain}
          </TemplateStyleTabsTrigger>
          <TemplateStyleTabsTrigger
            value="cover"
            disabled={isReadonly}
            style={{ flex: 1 }}
          >
            {t.imageFitCover}
          </TemplateStyleTabsTrigger>
        </TemplateStyleTabsList>
      </Field>
      <TemplateStyleTabsContent
        value={image.objectFit}
        keepMounted
        className="template-control-stack template-image-properties"
      >
        <TemplateImageGeometryFields {...props} />
        <Separator />
        <TemplateImageAppearanceFields {...props} />
        <TemplateImageBorderFields {...props} />
      </TemplateStyleTabsContent>
    </TemplateStyleTabs>
  );
}
