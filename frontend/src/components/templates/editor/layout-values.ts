import { createTemplateLayout } from "@/lib/templates";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
} from "@/types/resume";

export type TemplateContentDensityPreset = "compact" | "standard" | "relaxed";
type TemplateContentDensity = TemplateContentDensityPreset | "custom";
export type TemplateDividerStyle = "thin" | "medium" | "bold";
export type TemplateAvatarSizePreset = "small" | "standard" | "large";
type TemplateAvatarSize = TemplateAvatarSizePreset | "custom";

const avatarSizeScalePercentValues: Record<TemplateAvatarSizePreset, number> = {
  small: 85,
  standard: 100,
  large: 115,
};

export const dividerStyleValues: Record<TemplateDividerStyle, number> = {
  thin: 1,
  medium: 1.5,
  bold: 2.5,
};

export const contentDensityValues: Record<
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

export function getAvatarSizeLayout(
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

export function getAvatarSize(
  template: ResumeTemplateDefinition,
): TemplateAvatarSize {
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

export function getDividerStyle(
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

export function getContentDensity(
  settings: ResumeTemplateSettings,
): TemplateContentDensity {
  const densities = Object.keys(
    contentDensityValues,
  ) as TemplateContentDensityPreset[];

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
