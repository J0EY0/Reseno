import type { ResumeTemplateSettings } from "@/types/resume";
import { getResumeFontSizeInPoints } from "@/lib/templates";

import {
  TemplateStyleTabs,
  TemplateStyleTabsContent,
  TemplateStyleTabsList,
  TemplateStyleTabsTrigger,
} from "../template-style-tabs";
import type { TemplateEditorMessages } from "./editor-messages";
import { TemplateControlSection, TemplateSliderField } from "./editor-fields";
import { TemplatePageMarginField } from "./page-margin-field";
import { contentDensityValues, getContentDensity } from "./layout-values";

export function TemplateSpacingFields({
  t,
  settings,
  fontSize,
  disabled,
  onChange,
}: {
  t: TemplateEditorMessages;
  settings: ResumeTemplateSettings;
  fontSize: number;
  disabled: boolean;
  onChange: (patch: Partial<ResumeTemplateSettings>) => void;
}) {
  const density = getContentDensity(settings);
  const densityOptions = [
    ["compact", t.templatePresetCompact],
    ["standard", t.templatePresetStandard],
    ["relaxed", t.templatePresetRelaxed],
  ] as const;
  const selectedPreset = density === "custom" ? null : density;

  return (
    <TemplateControlSection title={t.templatePageSpacing}>
      <TemplateStyleTabs
        value={selectedPreset}
        className="flex min-w-0 flex-col gap-3"
        onValueChange={(value: unknown) => {
          if (
            !disabled &&
            (value === "compact" || value === "standard" || value === "relaxed")
          ) {
            onChange(contentDensityValues[value]);
          }
        }}
      >
        <TemplateStyleTabsList size="sm" aria-label={t.templateContentDensity}>
          {densityOptions.map(([value, label]) => (
            <TemplateStyleTabsTrigger
              key={value}
              value={value}
              disabled={disabled}
              style={{ flex: 1 }}
            >
              {label}
            </TemplateStyleTabsTrigger>
          ))}
        </TemplateStyleTabsList>
        <TemplateStyleTabsContent
          value={selectedPreset}
          keepMounted
          aria-label={t.templatePageSpacing}
          className="flex flex-col gap-2.5"
        >
          <TemplatePageMarginField
            t={t}
            settings={settings}
            disabled={disabled}
            onChange={onChange}
          />
          <TemplateSliderField
            label={t.lineSpacing}
            min={1.1}
            max={2.2}
            step={0.05}
            value={settings.bodyLineHeight}
            unit="pt"
            displayScale={getResumeFontSizeInPoints(fontSize)}
            displayPrecision={1}
            disabled={disabled}
            onChange={(value) => onChange({ bodyLineHeight: value })}
          />
        </TemplateStyleTabsContent>
      </TemplateStyleTabs>
    </TemplateControlSection>
  );
}
