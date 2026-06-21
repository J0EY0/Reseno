import type { AgentSettings, ModelConfig } from '@/types/resume'

export function createDefaultAgentSettings(
  modelConfigs: ModelConfig[] = [],
): AgentSettings {
  return {
    defaultModelId: modelConfigs[0]?.id ?? '',
    responseLanguage: 'follow',
    behaviorMode: 'balanced',
    confirmationMode: 'always',
  }
}

export function normalizeAgentSettings(
  value: unknown,
  modelConfigs: ModelConfig[] = [],
): AgentSettings {
  const defaults = createDefaultAgentSettings(modelConfigs)

  if (!value || typeof value !== 'object') {
    return defaults
  }

  const raw = value as Partial<AgentSettings>
  const rawDefaultModelId =
    typeof raw.defaultModelId === 'string' ? raw.defaultModelId : ''
  const hasDefaultModel = modelConfigs.some(
    (config) => config.id === rawDefaultModelId,
  )

  return {
    defaultModelId: hasDefaultModel ? rawDefaultModelId : defaults.defaultModelId,
    responseLanguage:
      raw.responseLanguage === 'zh' ||
      raw.responseLanguage === 'en' ||
      raw.responseLanguage === 'follow'
        ? raw.responseLanguage
        : defaults.responseLanguage,
    behaviorMode:
      raw.behaviorMode === 'strict' ||
      raw.behaviorMode === 'aggressive' ||
      raw.behaviorMode === 'balanced'
        ? raw.behaviorMode
        : defaults.behaviorMode,
    confirmationMode:
      raw.confirmationMode === 'suggestOnly' || raw.confirmationMode === 'always'
        ? raw.confirmationMode
        : defaults.confirmationMode,
  }
}
