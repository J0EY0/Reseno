import type { AppMessages } from '@/i18n'
import { createId } from '@/lib/resume'
import type {
  BuiltinResumeTemplateId,
  DeletedResumeTemplateDefinition,
  ResumeAvatarPosition,
  ResumeAvatarShape,
  ResumeFontFamily,
  ResumeTemplateLayout,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeTemplateImageElement,
  ResumeTemplateImageFit,
  ResumeTemplateSettings,
  ResumeTypographySettings,
} from '@/types/resume'

export const builtinTemplateIds: BuiltinResumeTemplateId[] = [
  'minimal',
  'modern',
  'compact',
]

const templateSettingsByPreset: Record<
  BuiltinResumeTemplateId,
  ResumeTemplateSettings
> = {
  minimal: {
    pagePaddingTop: 14,
    pagePaddingX: 12,
    pagePaddingBottom: 12,
    sectionGap: 1.4,
    itemGap: 1,
    bodyLineHeight: 1.8,
    nameScale: 2.15,
    sectionTitleScale: 1.28,
    itemTitleScale: 1.02,
    metaScale: 0.92,
    bodyScale: 0.96,
    pageBackground: '#ffffff',
    surfaceColor: '#f8fafc',
    headingColor: '#111827',
    bodyColor: '#334155',
    mutedColor: '#64748b',
    dividerColor: '#202020',
    dividerThickness: 1,
  },
  modern: {
    pagePaddingTop: 12,
    pagePaddingX: 12,
    pagePaddingBottom: 12,
    sectionGap: 1.3,
    itemGap: 0.95,
    bodyLineHeight: 1.72,
    nameScale: 2.25,
    sectionTitleScale: 0.82,
    itemTitleScale: 1.04,
    metaScale: 0.92,
    bodyScale: 0.95,
    pageBackground: '#ffffff',
    surfaceColor: '#f8fafc',
    headingColor: '#2563eb',
    bodyColor: '#475569',
    mutedColor: '#64748b',
    dividerColor: '#3b82f6',
    dividerThickness: 1,
  },
  compact: {
    pagePaddingTop: 11,
    pagePaddingX: 10,
    pagePaddingBottom: 10,
    sectionGap: 1.05,
    itemGap: 0.82,
    bodyLineHeight: 1.66,
    nameScale: 1.9,
    sectionTitleScale: 0.98,
    itemTitleScale: 1,
    metaScale: 0.9,
    bodyScale: 0.94,
    pageBackground: '#ffffff',
    surfaceColor: '#be123c',
    headingColor: '#be123c',
    bodyColor: '#18181b',
    mutedColor: '#71717a',
    dividerColor: '#be123c',
    dividerThickness: 1,
  },
}

const templateTypographyByPreset: Record<
  BuiltinResumeTemplateId,
  ResumeTypographySettings
> = {
  minimal: {
    fontFamily: 'inter',
    fontSize: 16,
  },
  modern: {
    fontFamily: 'serif',
    fontSize: 16,
  },
  compact: {
    fontFamily: 'plex',
    fontSize: 14,
  },
}

const templateLayoutByPreset: Record<
  BuiltinResumeTemplateId,
  ResumeTemplateLayout
> = {
  minimal: {
    basicInfo: 'centered',
    section: 'ruled',
    avatarPosition: 'right',
    avatarShape: 'rounded',
    avatarWidth: 25,
    avatarHeight: 32,
    avatarOffsetX: 0,
    avatarOffsetY: 0,
    avatarBorderWidth: 0,
    avatarBorderColor: '#e5e7eb',
    images: [],
  },
  modern: {
    basicInfo: 'profile',
    section: 'accent',
    avatarPosition: 'center',
    avatarShape: 'circle',
    avatarWidth: 30,
    avatarHeight: 30,
    avatarOffsetX: 0,
    avatarOffsetY: 0,
    avatarBorderWidth: 4,
    avatarBorderColor: '#ffffff',
    images: [],
  },
  compact: {
    basicInfo: 'sidebar',
    section: 'accent',
    avatarPosition: 'center',
    avatarShape: 'square',
    avatarWidth: 26,
    avatarHeight: 32,
    avatarOffsetX: 0,
    avatarOffsetY: 0,
    avatarBorderWidth: 0,
    avatarBorderColor: '#ffffff',
    images: [],
  },
}

const supportedFontFamilies: ResumeFontFamily[] = ['inter', 'serif', 'plex']
const fontSizeOptions = [12, 14, 16, 18, 20] as const

function clampNumber(
  value: number,
  min: number,
  max: number,
  step = 0.1,
) {
  const safe = Number.isFinite(value) ? value : min
  const normalized = Math.min(max, Math.max(min, safe))
  const precision = step >= 1 ? 1 : Math.round(1 / step)
  return Math.round(normalized * precision) / precision
}

function normalizeHexColor(value: unknown, fallback: string) {
  if (typeof value !== 'string') {
    return fallback
  }

  const normalized = value.trim()

  if (!/^#([\da-fA-F]{3}|[\da-fA-F]{6})$/.test(normalized)) {
    return fallback
  }

  if (normalized.length === 4) {
    return `#${normalized
      .slice(1)
      .split('')
      .map((char) => `${char}${char}`)
      .join('')
      .toLowerCase()}`
  }

  return normalized.toLowerCase()
}

function normalizeFontSize(value: unknown, fallback: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return fallback
  }

  return fontSizeOptions.reduce((closest, current) =>
    Math.abs(current - value) < Math.abs(closest - value) ? current : closest,
  )
}

function normalizeTemplateImageFit(value: unknown): ResumeTemplateImageFit {
  return value === 'cover' ? 'cover' : 'contain'
}

function normalizeTemplateImages(value: unknown): ResumeTemplateImageElement[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value
    .filter((item): item is Partial<ResumeTemplateImageElement> =>
      Boolean(item && typeof item === 'object'),
    )
    .map((item) => ({
      id:
        typeof item.id === 'string' && item.id.trim()
          ? item.id
          : createId('image'),
      name:
        typeof item.name === 'string' && item.name.trim()
          ? item.name.trim()
          : 'Image',
      src: typeof item.src === 'string' ? item.src.trim() : '',
      alt: typeof item.alt === 'string' ? item.alt.trim() : '',
      x: clampNumber(Number(item.x), 0, 210, 0.5),
      y: clampNumber(Number(item.y), 0, 297, 0.5),
      width: clampNumber(Number(item.width), 6, 120, 0.5),
      height: clampNumber(Number(item.height), 6, 120, 0.5),
      opacity: clampNumber(Number(item.opacity), 0.05, 1, 0.05),
      borderWidth: clampNumber(Number(item.borderWidth), 0, 8, 0.5),
      borderColor: normalizeHexColor(item.borderColor, '#e5e7eb'),
      borderRadius: clampNumber(Number(item.borderRadius), 0, 32, 1),
      objectFit: normalizeTemplateImageFit(item.objectFit),
      visible: typeof item.visible === 'boolean' ? item.visible : true,
    }))
}

function createTemplateTypography(
  preset: BuiltinResumeTemplateId,
  overrides: Partial<ResumeTypographySettings> = {},
): ResumeTypographySettings {
  const defaults = templateTypographyByPreset[preset]
  const nextFontFamily = supportedFontFamilies.includes(
    overrides.fontFamily as ResumeFontFamily,
  )
    ? (overrides.fontFamily as ResumeFontFamily)
    : defaults.fontFamily

  return {
    fontFamily: nextFontFamily,
    fontSize: normalizeFontSize(overrides.fontSize, defaults.fontSize),
  }
}

export function isBuiltinTemplateId(id: string): id is BuiltinResumeTemplateId {
  return builtinTemplateIds.includes(id as BuiltinResumeTemplateId)
}

export function createTemplateLayout(
  preset: BuiltinResumeTemplateId,
  overrides: Partial<ResumeTemplateLayout> = {},
): ResumeTemplateLayout {
  const defaults = templateLayoutByPreset[preset]
  const basicInfo =
    overrides.basicInfo === 'centered' ||
    overrides.basicInfo === 'profile' ||
    overrides.basicInfo === 'sidebar'
      ? overrides.basicInfo
      : defaults.basicInfo
  const section =
    overrides.section === 'ruled' ||
    overrides.section === 'boxed' ||
    overrides.section === 'accent' ||
    overrides.section === 'plain' ||
    overrides.section === 'band'
      ? overrides.section
      : defaults.section
  const avatarPosition =
    overrides.avatarPosition === 'right' ||
    overrides.avatarPosition === 'left' ||
    overrides.avatarPosition === 'center'
      ? (overrides.avatarPosition as ResumeAvatarPosition)
      : defaults.avatarPosition
  const avatarShape =
    overrides.avatarShape === 'rounded' ||
    overrides.avatarShape === 'circle' ||
    overrides.avatarShape === 'square'
      ? (overrides.avatarShape as ResumeAvatarShape)
      : defaults.avatarShape

  return {
    basicInfo,
    section,
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
  }
}

export function createTemplateSettings(
  preset: BuiltinResumeTemplateId,
  overrides: Partial<ResumeTemplateSettings> = {},
): ResumeTemplateSettings {
  const defaults = templateSettingsByPreset[preset]

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
      0.8,
      2.4,
      0.1,
    ),
    itemGap: clampNumber(overrides.itemGap ?? defaults.itemGap, 0.4, 1.8, 0.1),
    bodyLineHeight: clampNumber(
      overrides.bodyLineHeight ?? defaults.bodyLineHeight,
      1.4,
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
  }
}

export function getBuiltInTemplates(t: AppMessages): ResumeTemplateDefinition[] {
  return builtinTemplateIds.map((id) => ({
    id,
    preset: id,
    name: t.templateCards[id].name,
    description: t.templateCards[id].description,
    layout: createTemplateLayout(id),
    typography: createTemplateTypography(id),
    settings: createTemplateSettings(id),
    updatedAt: '',
    isBuiltIn: true,
  }))
}

export function normalizeTemplateDefinition(
  value: unknown,
): ResumeTemplateDefinition | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const raw = value as Partial<ResumeTemplateDefinition> & {
    settings?: Partial<ResumeTemplateSettings>
    layout?: Partial<ResumeTemplateLayout>
    typography?: Partial<ResumeTypographySettings>
  }

  const preset = isBuiltinTemplateId(String(raw.preset))
    ? (raw.preset as BuiltinResumeTemplateId)
    : 'minimal'
  const isBuiltIn =
    typeof raw.isBuiltIn === 'boolean'
      ? raw.isBuiltIn
      : typeof raw.id === 'string' && isBuiltinTemplateId(raw.id)

  return {
    id:
      typeof raw.id === 'string' &&
      raw.id.trim() &&
      (isBuiltIn || !isBuiltinTemplateId(raw.id))
        ? raw.id
        : createId('template'),
    preset,
    name:
      typeof raw.name === 'string' && raw.name.trim()
        ? raw.name.trim()
        : 'Custom Template',
    description:
      typeof raw.description === 'string' ? raw.description.trim() : '',
    layout: createTemplateLayout(preset, raw.layout ?? {}),
    typography: createTemplateTypography(preset, raw.typography ?? {}),
    settings: createTemplateSettings(preset, raw.settings ?? {}),
    updatedAt:
      typeof raw.updatedAt === 'string' && raw.updatedAt.trim()
        ? raw.updatedAt
        : new Date().toISOString(),
    isBuiltIn,
  }
}

export function normalizeCustomTemplates(source: unknown) {
  const rawTemplates =
    source &&
    typeof source === 'object' &&
    'customTemplates' in source &&
    Array.isArray((source as { customTemplates?: unknown[] }).customTemplates)
      ? (source as { customTemplates: unknown[] }).customTemplates
      : source &&
          typeof source === 'object' &&
          'templates' in source &&
          Array.isArray((source as { templates?: unknown[] }).templates)
        ? (source as { templates: unknown[] }).templates
      : Array.isArray(source)
        ? source
        : source && typeof source === 'object'
          ? [source]
        : []

  return rawTemplates
    .map((item) => normalizeTemplateDefinition(item))
    .filter((item): item is ResumeTemplateDefinition => Boolean(item))
}

export function normalizeDeletedTemplates(source: unknown) {
  const rawTemplates =
    source &&
    typeof source === 'object' &&
    'deletedTemplates' in source &&
    Array.isArray((source as { deletedTemplates?: unknown[] }).deletedTemplates)
      ? (source as { deletedTemplates: unknown[] }).deletedTemplates
      : []

  const deletedTemplates: DeletedResumeTemplateDefinition[] = []

  for (const value of rawTemplates) {
    if (!value || typeof value !== 'object') {
      continue
    }

    const deletedAt =
      typeof (value as { deletedAt?: string }).deletedAt === 'string' &&
      (value as { deletedAt?: string }).deletedAt?.trim()
        ? (value as { deletedAt: string }).deletedAt
        : new Date().toISOString()
    const normalized = normalizeTemplateDefinition(value)

    if (!normalized) {
      continue
    }

    deletedTemplates.push({
      ...normalized,
      isBuiltIn:
        typeof (value as { isBuiltIn?: unknown }).isBuiltIn === 'boolean'
          ? Boolean((value as { isBuiltIn: boolean }).isBuiltIn)
          : false,
      deletedAt,
    })
  }

  return deletedTemplates
}

export function getTemplateCatalog(
  t: AppMessages,
  customTemplates: ResumeTemplateDefinition[],
  hiddenTemplateIds: string[] = [],
) {
  const hiddenSet = new Set(hiddenTemplateIds)
  return [...getBuiltInTemplates(t), ...customTemplates].filter(
    (item) => !hiddenSet.has(item.id),
  )
}

export function getTemplateById(
  templates: ResumeTemplateDefinition[],
  templateId: ResumeTemplateId | null | undefined,
  fallbackTemplateId?: ResumeTemplateId | null,
) {
  return (
    templates.find((item) => item.id === templateId) ??
    templates.find((item) => item.id === fallbackTemplateId) ??
    templates.find((item) => item.id === 'minimal') ??
    templates[0]
  )
}

export function createCustomTemplateFromBase(
  base: ResumeTemplateDefinition,
  overrides: Partial<Pick<ResumeTemplateDefinition, 'name' | 'description'>> = {},
): ResumeTemplateDefinition {
  return {
    id: createId('template'),
    preset: base.preset,
    name: overrides.name?.trim() || `${base.name} Copy`,
    description: overrides.description?.trim() || base.description,
    layout: createTemplateLayout(base.preset, base.layout),
    typography: { ...base.typography },
    settings: createTemplateSettings(base.preset, base.settings),
    updatedAt: new Date().toISOString(),
    isBuiltIn: false,
  }
}
