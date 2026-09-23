import { useId, useState } from "react";

import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import type { ResumeTemplateDefinition } from "@/types/resume";

import { TemplateNumberInput, TemplateSelectField } from "./editor-fields";
import type { TemplateEditorMessages } from "./editor-messages";
import { getAvatarSize, getAvatarSizeLayout } from "./layout-values";
import TemplateFieldsPanel from "./template-fields-panel";

export function TemplateAvatarFields({
  t,
  template,
  onChange,
}: {
  t: TemplateEditorMessages;
  template: ResumeTemplateDefinition;
  onChange: (patch: Partial<ResumeTemplateDefinition["layout"]>) => void;
}) {
  const id = useId();
  const [custom, setCustom] = useState(false);
  const isReadonly = Boolean(template.isBuiltIn);
  const hasAvatar = template.layout.avatarPosition !== "none";
  const size = custom ? "custom" : getAvatarSize(template);

  return (
    <div className="px-0.5">
      <FieldGroup className="template-field-pair">
        <TemplateSelectField
          label={t.avatarPosition}
          value={template.layout.avatarPosition}
          disabled={isReadonly}
          onChange={(value) => onChange({ avatarPosition: value })}
          options={[
            { value: "none", label: t.avatarPositionNone },
            { value: "left", label: t.avatarPositionLeft },
            { value: "center", label: t.avatarPositionCenter },
            { value: "right", label: t.avatarPositionRight },
          ]}
        />
        {hasAvatar ? (
          <TemplateSelectField
            label={t.avatarSize}
            value={size}
            disabled={isReadonly}
            onChange={(value) => {
              setCustom(value === "custom");
              if (value !== "custom")
                onChange(getAvatarSizeLayout(template.preset, value));
            }}
            options={[
              { value: "small", label: t.avatarSizeSmall },
              { value: "standard", label: t.avatarSizeStandard },
              { value: "large", label: t.avatarSizeLarge },
              { value: "custom", label: t.templateCustomValue },
            ]}
          />
        ) : null}
      </FieldGroup>
      <TemplateFieldsPanel open={hasAvatar && size === "custom"}>
        <FieldGroup className="template-field-pair pt-2.5">
          {(
            [
              ["avatarWidth", t.imageWidth, t.avatarWidth, 48],
              ["avatarHeight", t.imageHeight, t.avatarHeight, 56],
            ] as const
          ).map(([key, label, accessibleLabel, max]) => (
            <Field
              key={key}
              orientation="horizontal"
              className="template-field-row"
              data-disabled={isReadonly}
            >
              <FieldLabel
                htmlFor={`${id}-${key}`}
                className="template-control-label"
              >
                {label}
              </FieldLabel>
              <TemplateNumberInput
                id={`${id}-${key}`}
                label={accessibleLabel}
                value={template.layout[key]}
                min={16}
                max={max}
                step={0.5}
                unit="mm"
                disabled={isReadonly}
                onChange={(value) => onChange({ [key]: value })}
              />
            </Field>
          ))}
        </FieldGroup>
      </TemplateFieldsPanel>
    </div>
  );
}
