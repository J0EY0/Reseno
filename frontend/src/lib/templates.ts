import type { AppMessages } from "@/i18n";
import {
  builtinTemplateIds,
  getBuiltinTemplatePreset,
} from "@/lib/template-presets";
import { createId } from "@/lib/resume";
import type {
  BuiltinResumeTemplateId,
  ResumeAvatarPosition,
  ResumeAvatarShape,
  ResumeListItemLayout,
  ResumeTemplateLayout,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeTemplateImageElement,
  ResumeTemplateImageFit,
  ResumeTemplateSettings,
  ResumeTimelineItemLayout,
} from "@/types/resume";

export const resumeFontSizeOptions = [12, 14, 16, 18, 20] as const;

const CSS_POINTS_PER_PIXEL = 72 / 96;

/**
 * Typography is persisted in CSS pixels for compatibility with existing
 * resumes. Document controls expose the equivalent point size expected by
 * users of print-oriented software without changing the rendered layout.
 */
export function getResumeFontSizeInPoints(fontSize: number) {
  return Number((fontSize * CSS_POINTS_PER_PIXEL).toFixed(2));
}

function clampNumber(value: number, min: number, max: number, step = 0.1) {
  const safe = Number.isFinite(value) ? value : min;
  const normalized = Math.min(max, Math.max(min, safe));
  const precision = step >= 1 ? 1 : Math.round(1 / step);
  return Math.round(normalized * precision) / precision;
}

function normalizeHexColor(value: unknown, fallback: string) {
  if (typeof value !== "string") {
    return fallback;
  }

  const normalized = value.trim();

  if (!/^#([\da-fA-F]{3}|[\da-fA-F]{6})$/.test(normalized)) {
    return fallback;
  }

  if (normalized.length === 4) {
    return `#${normalized
      .slice(1)
      .split("")
      .map((char) => `${char}${char}`)
      .join("")
      .toLowerCase()}`;
  }

  return normalized.toLowerCase();
}

export const DEFAULT_TEMPLATE_IMAGE = {
  src: "",
  alt: "",
  x: 166,
  y: 18,
  width: 30,
  height: 20,
  opacity: 1,
  borderWidth: 0.8,
  borderColor: "#d4d4d8",
  borderRadius: 8,
  objectFit: "contain",
  visible: true,
} satisfies Omit<ResumeTemplateImageElement, "id" | "name">;

export function createTemplateImageElement(
  index: number,
  defaultName: string,
  layout?: Pick<ResumeTemplateLayout, "avatarPosition">,
): ResumeTemplateImageElement {
  return {
    ...DEFAULT_TEMPLATE_IMAGE,
    id: createId("image"),
    name: `${defaultName} ${index}`,
    x: layout?.avatarPosition === "right" ? 14 : DEFAULT_TEMPLATE_IMAGE.x,
  };
}

function normalizeTemplateImageFit(value: unknown): ResumeTemplateImageFit {
  return value === "cover" ? "cover" : DEFAULT_TEMPLATE_IMAGE.objectFit;
}

function normalizeTemplateImageSource(value: unknown) {
  if (typeof value !== "string") {
    return "";
  }

  const source = value.trim();
  return source.startsWith("data:image/") ? source : "";
}

function normalizeTimelineItemLayout(
  value: unknown,
  fallback: ResumeTimelineItemLayout,
): ResumeTimelineItemLayout {
  return value === "split" || value === "stacked" || value === "compact"
    ? value
    : fallback;
}

function normalizeListItemLayout(
  value: unknown,
  fallback: ResumeListItemLayout,
): ResumeListItemLayout {
  return value === "list" || value === "inline" || value === "columns"
    ? value
    : fallback;
}

function normalizeTemplateImages(value: unknown): ResumeTemplateImageElement[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .filter((item): item is Partial<ResumeTemplateImageElement> =>
      Boolean(item && typeof item === "object"),
    )
    .map((item) => ({
      id:
        typeof item.id === "string" && item.id.trim()
          ? item.id
          : createId("image"),
      name:
        typeof item.name === "string" && item.name.trim()
          ? item.name.trim()
          : "Image",
      src: normalizeTemplateImageSource(item.src),
      alt: typeof item.alt === "string" ? item.alt.trim() : "",
      x: clampNumber(Number(item.x ?? DEFAULT_TEMPLATE_IMAGE.x), 0, 210, 0.5),
      y: clampNumber(Number(item.y ?? DEFAULT_TEMPLATE_IMAGE.y), 0, 297, 0.5),
      width: clampNumber(
        Number(item.width ?? DEFAULT_TEMPLATE_IMAGE.width),
        6,
        120,
        0.5,
      ),
      height: clampNumber(
        Number(item.height ?? DEFAULT_TEMPLATE_IMAGE.height),
        6,
        120,
        0.5,
      ),
      opacity: clampNumber(
        Number(item.opacity ?? DEFAULT_TEMPLATE_IMAGE.opacity),
        0.05,
        1,
        0.05,
      ),
      borderWidth: clampNumber(
        Number(item.borderWidth ?? DEFAULT_TEMPLATE_IMAGE.borderWidth),
        0,
        8,
        0.1,
      ),
      borderColor: normalizeHexColor(
        item.borderColor,
        DEFAULT_TEMPLATE_IMAGE.borderColor,
      ),
      borderRadius: clampNumber(
        Number(item.borderRadius ?? DEFAULT_TEMPLATE_IMAGE.borderRadius),
        0,
        32,
        1,
      ),
      objectFit: normalizeTemplateImageFit(item.objectFit),
      visible: typeof item.visible === "boolean" ? item.visible : true,
    }));
}

export function createTemplateLayout(
  preset: BuiltinResumeTemplateId,
  overrides: Partial<ResumeTemplateLayout> = {},
): ResumeTemplateLayout {
  const defaults = getBuiltinTemplatePreset(preset).layout;
  const basicInfo =
    overrides.basicInfo === "centered" ||
    overrides.basicInfo === "left" ||
    overrides.basicInfo === "split" ||
    overrides.basicInfo === "profile" ||
    overrides.basicInfo === "sidebar"
      ? overrides.basicInfo
      : defaults.basicInfo;
  const section =
    overrides.section === "ruled" ||
    overrides.section === "underlined" ||
    overrides.section === "boxed" ||
    overrides.section === "accent" ||
    overrides.section === "plain" ||
    overrides.section === "band"
      ? overrides.section
      : defaults.section;
  const avatarPosition =
    overrides.avatarPosition === "none" ||
    overrides.avatarPosition === "right" ||
    overrides.avatarPosition === "left" ||
    overrides.avatarPosition === "center"
      ? (overrides.avatarPosition as ResumeAvatarPosition)
      : defaults.avatarPosition;
  const avatarShape =
    overrides.avatarShape === "rounded" ||
    overrides.avatarShape === "circle" ||
    overrides.avatarShape === "square"
      ? (overrides.avatarShape as ResumeAvatarShape)
      : defaults.avatarShape;

  return {
    basicInfo,
    section,
    timelineItemLayout: normalizeTimelineItemLayout(
      overrides.timelineItemLayout,
      defaults.timelineItemLayout,
    ),
    listItemLayout: normalizeListItemLayout(
      overrides.listItemLayout,
      defaults.listItemLayout,
    ),
    avatarPosition,
    avatarShape,
    avatarWidth: clampNumber(
      overrides.avatarWidth ?? defaults.avatarWidth,
      16,
      48,
      0.5,
    ),
    avatarHeight: clampNumber(
      overrides.avatarHeight ?? defaults.avatarHeight,
      16,
      56,
      0.5,
    ),
    avatarOffsetX: clampNumber(
      overrides.avatarOffsetX ?? defaults.avatarOffsetX,
      -40,
      40,
      0.5,
    ),
    avatarOffsetY: clampNumber(
      overrides.avatarOffsetY ?? defaults.avatarOffsetY,
      -40,
      40,
      0.5,
    ),
    avatarBorderWidth: clampNumber(
      overrides.avatarBorderWidth ?? defaults.avatarBorderWidth,
      0,
      8,
      0.5,
    ),
    avatarBorderColor: normalizeHexColor(
      overrides.avatarBorderColor,
      defaults.avatarBorderColor,
    ),
    images: normalizeTemplateImages(overrides.images ?? defaults.images),
  };
}

export function createTemplateSettings(
  preset: BuiltinResumeTemplateId,
  overrides: Partial<ResumeTemplateSettings> = {},
): ResumeTemplateSettings {
  const defaults = getBuiltinTemplatePreset(preset).settings;

  return {
    pagePaddingTop: clampNumber(
      overrides.pagePaddingTop ?? defaults.pagePaddingTop,
      8,
      20,
      1,
    ),
    pagePaddingX: clampNumber(
      overrides.pagePaddingX ?? defaults.pagePaddingX,
      8,
      18,
      1,
    ),
    pagePaddingBottom: clampNumber(
      overrides.pagePaddingBottom ?? defaults.pagePaddingBottom,
      8,
      18,
      1,
    ),
    sectionGap: clampNumber(
      overrides.sectionGap ?? defaults.sectionGap,
      0.6,
      2.4,
      0.1,
    ),
    itemGap: clampNumber(overrides.itemGap ?? defaults.itemGap, 0.4, 1.8, 0.1),
    bodyLineHeight: clampNumber(
      overrides.bodyLineHeight ?? defaults.bodyLineHeight,
      1.1,
      2.2,
      0.05,
    ),
    nameScale: clampNumber(
      overrides.nameScale ?? defaults.nameScale,
      1.6,
      2.8,
      0.05,
    ),
    sectionTitleScale: clampNumber(
      overrides.sectionTitleScale ?? defaults.sectionTitleScale,
      0.75,
      1.6,
      0.05,
    ),
    itemTitleScale: clampNumber(
      overrides.itemTitleScale ?? defaults.itemTitleScale,
      0.85,
      1.4,
      0.05,
    ),
    metaScale: clampNumber(
      overrides.metaScale ?? defaults.metaScale,
      0.75,
      1.15,
      0.05,
    ),
    bodyScale: clampNumber(
      overrides.bodyScale ?? defaults.bodyScale,
      0.85,
      1.2,
      0.05,
    ),
    pageBackground: normalizeHexColor(
      overrides.pageBackground,
      defaults.pageBackground,
    ),
    surfaceColor: normalizeHexColor(
      overrides.surfaceColor,
      defaults.surfaceColor,
    ),
    headingColor: normalizeHexColor(
      overrides.headingColor,
      defaults.headingColor,
    ),
    bodyColor: normalizeHexColor(overrides.bodyColor, defaults.bodyColor),
    mutedColor: normalizeHexColor(overrides.mutedColor, defaults.mutedColor),
    dividerColor: normalizeHexColor(
      overrides.dividerColor,
      defaults.dividerColor,
    ),
    dividerThickness: clampNumber(
      overrides.dividerThickness ?? defaults.dividerThickness,
      0.5,
      3,
      0.5,
    ),
  };
}

export function getBuiltInTemplates(
  t: AppMessages,
): ResumeTemplateDefinition[] {
  return builtinTemplateIds.map((id) => ({
    id,
    preset: id,
    name: t.templateCards[id].name,
    description: t.templateCards[id].description,
    layout: createTemplateLayout(id),
    typography: { ...getBuiltinTemplatePreset(id).typography },
    settings: createTemplateSettings(id),
    updatedAt: "",
    isBuiltIn: true,
  }));
}

export function getTemplateCatalog(
  t: AppMessages,
  customTemplates: ResumeTemplateDefinition[],
) {
  return [...getBuiltInTemplates(t), ...customTemplates];
}

export function getTemplateById(
  templates: ResumeTemplateDefinition[],
  templateId: ResumeTemplateId | null | undefined,
) {
  const template =
    templates.find((item) => item.id === templateId) ??
    templates.find((item) => item.id === "minimal");

  if (!template) {
    throw new Error("The built-in Minimal template is missing.");
  }

  return template;
}

export function createCustomTemplateFromBase(
  base: ResumeTemplateDefinition,
  overrides: Partial<
    Pick<ResumeTemplateDefinition, "name" | "description">
  > = {},
): ResumeTemplateDefinition {
  return {
    id: createId("template"),
    preset: base.preset,
    name: overrides.name?.trim() || `${base.name} Copy`,
    description: overrides.description?.trim() || base.description,
    layout: createTemplateLayout(base.preset, base.layout),
    typography: { ...base.typography },
    settings: createTemplateSettings(base.preset, base.settings),
    updatedAt: new Date().toISOString(),
    isBuiltIn: false,
  };
}
