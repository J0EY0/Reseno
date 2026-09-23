import { Separator } from "@/components/ui/separator";
import { TemplateStyleTabsContent as TabsContent } from "../template-style-tabs";
import {
  getResumeFontSizeInPoints,
  resumeFontSizeOptions,
} from "@/lib/templates";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
} from "@/types/resume";

import type { TemplateEditorMessages } from "./editor-messages";
import {
  TemplateControlSection,
  TemplateSelectField,
  TemplateSliderField,
} from "./editor-fields";

export function TemplateTypographyTab({
  t,
  template,
  onUpdateTemplate,
}: {
  t: TemplateEditorMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: Partial<ResumeTemplateDefinition>) => void;
}) {
  const isReadonly = Boolean(template.isBuiltIn);
  const baseSizeInPoints = getResumeFontSizeInPoints(
    template.typography.fontSize,
  );

  function updateTypography(
    patch: Partial<ResumeTemplateDefinition["typography"]>,
  ) {
    if (!isReadonly)
      onUpdateTemplate({ typography: { ...template.typography, ...patch } });
  }
  function updateSettings(patch: Partial<ResumeTemplateSettings>) {
    if (!isReadonly)
      onUpdateTemplate({ settings: { ...template.settings, ...patch } });
  }

  return (
    <TabsContent
      animate
      value="typography"
      className="template-control-stack py-5"
    >
      <TemplateControlSection title={t.templateTypographyTab}>
        <TemplateSelectField
          label={t.fontFamily}
          value={template.typography.fontFamily}
          disabled={isReadonly}
          onChange={(value) => updateTypography({ fontFamily: value })}
          options={[
            { value: "inter", label: t.fontInter },
            { value: "noto_sans_sc", label: t.fontNotoSans },
            { value: "serif", label: t.fontSerif },
            { value: "times", label: t.fontTimes },
            { value: "plex", label: t.fontPlex },
          ]}
        />
        <TemplateSelectField
          label={t.fontSize}
          value={String(template.typography.fontSize)}
          disabled={isReadonly}
          onChange={(value) => updateTypography({ fontSize: Number(value) })}
          options={resumeFontSizeOptions.map((size) => ({
            value: String(size),
            label: `${getResumeFontSizeInPoints(size)} pt`,
          }))}
        />
      </TemplateControlSection>
      <Separator />
      <TemplateControlSection title={t.templateTypographyScale}>
        {(
          [
            ["nameScale", t.nameSize, 1.6, 2.8],
            ["sectionTitleScale", t.sectionTitleSize, 0.75, 1.6],
            ["itemTitleScale", t.itemTitleSize, 0.85, 1.4],
            ["metaScale", t.metaSize, 0.75, 1.15],
            ["bodyScale", t.bodySize, 0.85, 1.2],
          ] as const
        ).map(([key, label, min, max]) => (
          <TemplateSliderField
            key={key}
            label={label}
            min={min}
            max={max}
            step={0.05}
            value={template.settings[key]}
            displayScale={baseSizeInPoints}
            unit="pt"
            onChange={(value) => updateSettings({ [key]: value })}
            disabled={isReadonly}
          />
        ))}
      </TemplateControlSection>
    </TabsContent>
  );
}
