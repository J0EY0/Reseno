import {
  builtinTemplatePresets as generatedBuiltinTemplatePresets,
} from '@/lib/template-presets.generated'
import type {
  BuiltinResumeTemplateId,
  ResumeTemplateImageElement,
  ResumeTemplateLayout,
  ResumeTemplateSettings,
  ResumeTypographySettings,
} from '@/types/resume'

type BuiltinTemplateLayout = Omit<
  Readonly<ResumeTemplateLayout>,
  'images'
> & {
  readonly images: readonly ResumeTemplateImageElement[]
}

interface BuiltinTemplatePreset {
  readonly starter: 'earlyCareer' | 'experienced' | 'executive' | 'research'
  readonly layout: BuiltinTemplateLayout
  readonly typography: Readonly<ResumeTypographySettings>
  readonly settings: Readonly<ResumeTemplateSettings>
}

const builtinTemplatePresets: Readonly<
  Record<BuiltinResumeTemplateId, BuiltinTemplatePreset>
> = generatedBuiltinTemplatePresets

export const builtinTemplateIds = Object.keys(
  builtinTemplatePresets,
) as BuiltinResumeTemplateId[]

/** @internal Normalization owns the only consumer of preset implementation data. */
export function getBuiltinTemplatePreset(id: BuiltinResumeTemplateId) {
  return builtinTemplatePresets[id]
}

export function getBuiltinTemplateStarter(id: BuiltinResumeTemplateId) {
  return builtinTemplatePresets[id].starter
}

export function isBuiltinTemplateId(id: string): id is BuiltinResumeTemplateId {
  return builtinTemplateIds.includes(id as BuiltinResumeTemplateId)
}
