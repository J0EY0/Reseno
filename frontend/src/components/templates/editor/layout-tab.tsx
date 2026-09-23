import { Separator } from "@/components/ui/separator";
import { TemplateStyleTabsContent as TabsContent } from "../template-style-tabs";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
} from "@/types/resume";

import type { TemplateEditorMessages } from "./editor-messages";
import { TemplateControlSection, TemplateSelectField } from "./editor-fields";
import { TemplateSpacingFields } from "./layout-spacing-fields";
import { TemplateAvatarFields } from "./avatar-fields";
import { TemplateTimelineLayoutFields } from "./timeline-layout-fields";
import { TemplateLayoutOptionPreview } from "./template-layout-option-preview";
import { dividerStyleValues, getDividerStyle } from "./layout-values";

export function TemplateLayoutTab({
  t,
  template,
  onUpdateTemplate,
}: {
  t: TemplateEditorMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: Partial<ResumeTemplateDefinition>) => void;
}) {
  const isReadonly = Boolean(template.isBuiltIn);

  function updateSettings(patch: Partial<ResumeTemplateSettings>) {
    if (!isReadonly)
      onUpdateTemplate({ settings: { ...template.settings, ...patch } });
  }
  function updateLayout(patch: Partial<ResumeTemplateDefinition["layout"]>) {
    if (!isReadonly)
      onUpdateTemplate({ layout: { ...template.layout, ...patch } });
  }

  return (
    <TabsContent animate value="layout" className="template-control-stack py-5">
      <TemplateControlSection title={t.basicInfo}>
        <TemplateSelectField
          label={t.basicInfoLayout}
          value={template.layout.basicInfo}
          disabled={isReadonly}
          onChange={(value) => updateLayout({ basicInfo: value })}
          options={(
            [
              ["centered", t.basicInfoLayoutCentered],
              ["left", t.basicInfoLayoutLeft],
              ["split", t.basicInfoLayoutSplit],
              ["profile", t.basicInfoLayoutProfile],
              ["sidebar", t.basicInfoLayoutSidebar],
            ] as const
          ).map(([value, label]) => ({
            value,
            label,
            preview: (
              <TemplateLayoutOptionPreview kind="basicInfo" value={value} />
            ),
          }))}
        />
        <TemplateAvatarFields
          key={template.id}
          t={t}
          template={template}
          onChange={updateLayout}
        />
      </TemplateControlSection>
      <Separator />
      <TemplateControlSection title={t.templateContentStructure}>
        <TemplateSelectField
          label={t.sectionTemplateStyle}
          value={template.layout.section}
          disabled={isReadonly}
          onChange={(value) => updateLayout({ section: value })}
          options={(
            [
              ["ruled", t.sectionStyleRuled],
              ["underlined", t.sectionStyleUnderlined],
              ["boxed", t.sectionStyleBoxed],
              ["accent", t.sectionStyleAccent],
              ["plain", t.sectionStylePlain],
              ["band", t.sectionStyleBand],
            ] as const
          ).map(([value, label]) => ({
            value,
            label,
            preview: (
              <TemplateLayoutOptionPreview
                kind="section"
                value={
                  value === "accent" && template.layout.basicInfo === "sidebar"
                    ? "ruled"
                    : value
                }
              />
            ),
          }))}
        />
        <TemplateTimelineLayoutFields
          key={template.id}
          t={t}
          layout={template.layout}
          disabled={isReadonly}
          onChange={updateLayout}
        />
        <TemplateSelectField
          label={t.listItemLayout}
          value={template.layout.listItemLayout}
          disabled={isReadonly}
          onChange={(value) => updateLayout({ listItemLayout: value })}
          options={(
            [
              ["list", t.listItemLayoutList],
              ["inline", t.listItemLayoutInline],
              ["columns", t.listItemLayoutColumns],
            ] as const
          ).map(([value, label]) => ({
            value,
            label,
            preview: <TemplateLayoutOptionPreview kind="list" value={value} />,
          }))}
        />
        <TemplateSelectField
          label={t.templateDividerStyle}
          value={getDividerStyle(template.settings)}
          disabled={isReadonly}
          onChange={(value) =>
            updateSettings({ dividerThickness: dividerStyleValues[value] })
          }
          options={(
            [
              ["thin", t.templateDividerThin],
              ["medium", t.templateDividerMedium],
              ["bold", t.templateDividerBold],
            ] as const
          ).map(([value, label]) => ({
            value,
            label,
            preview: (
              <TemplateLayoutOptionPreview kind="divider" value={value} />
            ),
          }))}
        />
      </TemplateControlSection>
      <Separator />
      <TemplateSpacingFields
        t={t}
        settings={template.settings}
        fontSize={template.typography.fontSize}
        disabled={isReadonly}
        onChange={updateSettings}
      />
    </TabsContent>
  );
}
