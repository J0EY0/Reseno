import type { AgentSettings, ModelConfig } from '@/types/resume'

export function createDefaultAgentSettings(
  modelConfigs: ModelConfig[],
): AgentSettings {
  return {
    defaultModelId: modelConfigs[0]?.id ?? '',
    responseLanguage: 'follow',
    behaviorMode: 'balanced',
    autoRunMatch: true,
  }
}

export function normalizeAgentSettings(
  value: unknown,
  modelConfigs: ModelConfig[],
): AgentSettings {
  const defaults = createDefaultAgentSettings(modelConfigs)

  if (!value || typeof value !== 'object') {
    return defaults
  }

  const raw = value as Partial<AgentSettings>
  const defaultModelId =
    typeof raw.defaultModelId === 'string' &&
    modelConfigs.some((item) => item.id === raw.defaultModelId)
      ? raw.defaultModelId
      : defaults.defaultModelId

  return {
    defaultModelId,
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
    autoRunMatch:
      typeof raw.autoRunMatch === 'boolean'
        ? raw.autoRunMatch
        : defaults.autoRunMatch,
  }
}
