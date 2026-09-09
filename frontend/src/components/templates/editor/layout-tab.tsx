import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TabsContent } from "@/components/ui/tabs";
import type { AppMessages } from "@/i18n";
import { createTemplateLayout } from "@/lib/templates";
import type {
  ResumeAvatarPosition,
  ResumeBasicInfoLayout,
  ResumeListItemLayout,
  ResumeSectionTemplateStyle,
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
  ResumeTimelineItemLayout,
} from "@/types/resume";

import { TemplateSelectRow } from "./editor-fields";

type TemplatePageMarginPreset = "compact" | "standard" | "relaxed";
type TemplatePageMargin = TemplatePageMarginPreset | "custom";
type TemplateContentDensityPreset = "compact" | "standard" | "relaxed";
type TemplateContentDensity = TemplateContentDensityPreset | "custom";
type TemplateDividerStyle = "thin" | "medium" | "bold";
type TemplateAvatarSizePreset = "small" | "standard" | "large";
type TemplateAvatarSize = TemplateAvatarSizePreset | "custom";

const avatarSizeScalePercentValues: Record<TemplateAvatarSizePreset, number> = {
  small: 85,
  standard: 100,
  large: 115,
};

const pageMarginPresetValues: Record<
  TemplatePageMarginPreset,
  Pick<
    ResumeTemplateSettings,
    "pagePaddingTop" | "pagePaddingX" | "pagePaddingBottom"
  >
> = {
  compact: {
    pagePaddingTop: 10,
    pagePaddingX: 10,
    pagePaddingBottom: 10,
  },
  standard: {
    pagePaddingTop: 14,
    pagePaddingX: 12,
    pagePaddingBottom: 12,
  },
  relaxed: {
    pagePaddingTop: 18,
    pagePaddingX: 16,
    pagePaddingBottom: 16,
  },
};

const dividerStyleValues: Record<TemplateDividerStyle, number> = {
  thin: 1,
  medium: 1.5,
  bold: 2.5,
};

const contentDensityValues: Record<
  TemplateContentDensityPreset,
  Pick<ResumeTemplateSettings, "sectionGap" | "itemGap" | "bodyLineHeight">
> = {
  compact: {
    sectionGap: 0.9,
    itemGap: 0.6,
    bodyLineHeight: 1.45,
  },
  standard: {
    sectionGap: 1.2,
    itemGap: 0.8,
    bodyLineHeight: 1.6,
  },
  relaxed: {
    sectionGap: 1.5,
    itemGap: 1,
    bodyLineHeight: 1.75,
  },
};

function getAvatarSizeLayout(
  preset: ResumeTemplateDefinition["preset"],
  size: TemplateAvatarSizePreset,
): Pick<ResumeTemplateDefinition["layout"], "avatarWidth" | "avatarHeight"> {
  const defaults = createTemplateLayout(preset);
  const scalePercent = avatarSizeScalePercentValues[size];
  const scaled = createTemplateLayout(preset, {
    avatarWidth: (defaults.avatarWidth * scalePercent) / 100,
    avatarHeight: (defaults.avatarHeight * scalePercent) / 100,
  });

  return {
    avatarWidth: scaled.avatarWidth,
    avatarHeight: scaled.avatarHeight,
  };
}

function getAvatarSize(template: ResumeTemplateDefinition): TemplateAvatarSize {
  const sizes = Object.keys(
    avatarSizeScalePercentValues,
  ) as TemplateAvatarSizePreset[];

  return (
    sizes.find((size) => {
      const layout = getAvatarSizeLayout(template.preset, size);

      return (
        template.layout.avatarWidth === layout.avatarWidth &&
        template.layout.avatarHeight === layout.avatarHeight
      );
    }) ?? "custom"
  );
}

function getPageMarginPreset(
  settings: ResumeTemplateSettings,
): TemplatePageMargin {
  const presets = Object.keys(
    pageMarginPresetValues,
  ) as TemplatePageMarginPreset[];
  return (
    presets.find((name) => {
      const preset = pageMarginPresetValues[name];
      return (
        settings.pagePaddingTop === preset.pagePaddingTop &&
        settings.pagePaddingX === preset.pagePaddingX &&
        settings.pagePaddingBottom === preset.pagePaddingBottom
      );
    }) ?? "custom"
  );
}

function getDividerStyle(
  settings: ResumeTemplateSettings,
): TemplateDividerStyle {
  if (settings.dividerThickness >= 2) {
    return "bold";
  }

  if (settings.dividerThickness > 1) {
    return "medium";
  }

  return "thin";
}

function getContentDensity(
  settings: ResumeTemplateSettings,
): TemplateContentDensity {
  const densities = Object.keys(
    contentDensityValues,
  ) as TemplateContentDensityPreset[];

  // Numeric settings remain the source of truth. Manual tuning and Smart
  // One Page must not be mislabeled as the nearest named preset.
  return (
    densities.find((density) => {
      const preset = contentDensityValues[density];

      return (
        Math.abs(settings.sectionGap - preset.sectionGap) <= 0.01 &&
        Math.abs(settings.itemGap - preset.itemGap) <= 0.01 &&
        Math.abs(settings.bodyLineHeight - preset.bodyLineHeight) <= 0.01
      );
    }) ?? "custom"
  );
}

export function TemplateLayoutTab({
  t,
  template,
  onUpdateTemplate,
}: {
  t: AppMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: Partial<ResumeTemplateDefinition>) => void;
}) {
  const isReadonly = Boolean(template.isBuiltIn);

  function updateSettings(patch: Partial<ResumeTemplateSettings>) {
    if (isReadonly) {
      return;
    }

    onUpdateTemplate({
      settings: {
        ...template.settings,
        ...patch,
      },
    });
  }

  function updateLayout(patch: Partial<ResumeTemplateDefinition["layout"]>) {
    if (isReadonly) {
      return;
    }

    onUpdateTemplate({
      layout: {
        ...template.layout,
        ...patch,
      },
    });
  }

  function updateAvatarSize(size: TemplateAvatarSize) {
    if (size !== "custom") {
      updateLayout(getAvatarSizeLayout(template.preset, size));
    }
  }
  return (
    <TabsContent value="layout" className="m-0 px-1 py-4">
      <div className="grid">
        <TemplateSelectRow label={t.basicInfoLayout}>
          <Select
            value={template.layout.basicInfo}
            disabled={isReadonly}
            onValueChange={(value) =>
              updateLayout({ basicInfo: value as ResumeBasicInfoLayout })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectItem value="centered">
                {t.basicInfoLayoutCentered}
              </SelectItem>
              <SelectItem value="left">{t.basicInfoLayoutLeft}</SelectItem>
              <SelectItem value="split">{t.basicInfoLayoutSplit}</SelectItem>
              <SelectItem value="profile">
                {t.basicInfoLayoutProfile}
              </SelectItem>
              <SelectItem value="sidebar">
                {t.basicInfoLayoutSidebar}
              </SelectItem>
            </SelectContent>
          </Select>
        </TemplateSelectRow>

        <TemplateSelectRow label={t.sectionTemplateStyle}>
          <Select
            value={template.layout.section}
            disabled={isReadonly}
            onValueChange={(value) =>
              updateLayout({
                section: value as ResumeSectionTemplateStyle,
              })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectItem value="ruled">{t.sectionStyleRuled}</SelectItem>
              <SelectItem value="underlined">
                {t.sectionStyleUnderlined}
              </SelectItem>
              <SelectItem value="boxed">{t.sectionStyleBoxed}</SelectItem>
              <SelectItem value="accent">{t.sectionStyleAccent}</SelectItem>
              <SelectItem value="plain">{t.sectionStylePlain}</SelectItem>
              <SelectItem value="band">{t.sectionStyleBand}</SelectItem>
            </SelectContent>
          </Select>
        </TemplateSelectRow>

        <TemplateSelectRow label={t.timelineItemLayout}>
          <Select
            value={template.layout.timelineItemLayout}
            disabled={isReadonly}
            onValueChange={(value) =>
              updateLayout({
                timelineItemLayout: value as ResumeTimelineItemLayout,
              })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectItem value="split">{t.timelineItemLayoutSplit}</SelectItem>
              <SelectItem value="stacked">
                {t.timelineItemLayoutStacked}
              </SelectItem>
              <SelectItem value="compact">
                {t.timelineItemLayoutCompact}
              </SelectItem>
            </SelectContent>
          </Select>
        </TemplateSelectRow>

        <TemplateSelectRow label={t.listItemLayout}>
          <Select
            value={template.layout.listItemLayout}
            disabled={isReadonly}
            onValueChange={(value) =>
              updateLayout({
                listItemLayout: value as ResumeListItemLayout,
              })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectItem value="list">{t.listItemLayoutList}</SelectItem>
              <SelectItem value="inline">{t.listItemLayoutInline}</SelectItem>
              <SelectItem value="columns">{t.listItemLayoutColumns}</SelectItem>
            </SelectContent>
          </Select>
        </TemplateSelectRow>

        <TemplateSelectRow label={t.avatarPosition}>
          <Select
            value={template.layout.avatarPosition}
            disabled={isReadonly}
            onValueChange={(value) =>
              updateLayout({ avatarPosition: value as ResumeAvatarPosition })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectItem value="none">{t.avatarPositionNone}</SelectItem>
              <SelectItem value="right">{t.avatarPositionRight}</SelectItem>
              <SelectItem value="left">{t.avatarPositionLeft}</SelectItem>
              <SelectItem value="center">{t.avatarPositionCenter}</SelectItem>
            </SelectContent>
          </Select>
        </TemplateSelectRow>

        {template.layout.avatarPosition !== "none" ? (
          <TemplateSelectRow label={t.avatarSize}>
            <Select
              value={getAvatarSize(template)}
              disabled={isReadonly}
              onValueChange={(value) =>
                updateAvatarSize(value as TemplateAvatarSize)
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="end" position="popper" sideOffset={4}>
                <SelectItem value="small">{t.avatarSizeSmall}</SelectItem>
                <SelectItem value="standard">{t.avatarSizeStandard}</SelectItem>
                <SelectItem value="large">{t.avatarSizeLarge}</SelectItem>
                <SelectItem value="custom" disabled>
                  {t.avatarSizeCustom}
                </SelectItem>
              </SelectContent>
            </Select>
          </TemplateSelectRow>
        ) : null}

        <TemplateSelectRow label={t.pageMargin}>
          <Select
            value={getPageMarginPreset(template.settings)}
            disabled={isReadonly}
            onValueChange={(value) => {
              if (value !== "custom") {
                updateSettings(
                  pageMarginPresetValues[value as TemplatePageMarginPreset],
                );
              }
            }}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectItem value="compact">{t.pageMarginCompact}</SelectItem>
              <SelectItem value="standard">{t.pageMarginStandard}</SelectItem>
              <SelectItem value="relaxed">{t.pageMarginRelaxed}</SelectItem>
              <SelectItem value="custom" disabled>
                {t.templatePageMarginCustom}
              </SelectItem>
            </SelectContent>
          </Select>
        </TemplateSelectRow>

        <TemplateSelectRow label={t.templateContentDensity}>
          <Select
            value={getContentDensity(template.settings)}
            disabled={isReadonly}
            onValueChange={(value) => {
              if (value === "custom") {
                return;
              }

              updateSettings(
                contentDensityValues[value as TemplateContentDensityPreset],
              );
            }}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectItem value="compact">
                {t.templateDensityCompact}
              </SelectItem>
              <SelectItem value="standard">
                {t.templateDensityStandard}
              </SelectItem>
              <SelectItem value="relaxed">
                {t.templateDensityRelaxed}
              </SelectItem>
              <SelectItem value="custom" disabled>
                {t.templateDensityCustom}
              </SelectItem>
            </SelectContent>
          </Select>
        </TemplateSelectRow>

        <TemplateSelectRow label={t.templateDividerStyle}>
          <Select
            value={getDividerStyle(template.settings)}
            disabled={isReadonly}
            onValueChange={(value) =>
              updateSettings({
                dividerThickness:
                  dividerStyleValues[value as TemplateDividerStyle],
              })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectItem value="thin">{t.templateDividerThin}</SelectItem>
              <SelectItem value="medium">{t.templateDividerMedium}</SelectItem>
              <SelectItem value="bold">{t.templateDividerBold}</SelectItem>
            </SelectContent>
          </Select>
        </TemplateSelectRow>
      </div>
    </TabsContent>
  );
}
