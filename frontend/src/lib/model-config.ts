import type { Locale } from '@/i18n'
import {
  DEFAULT_MODEL_PROVIDER_ID,
  inferModelProviderId,
  normalizeProviderId,
} from '@/lib/model-providers'
import type { LegacyModelConfig, ModelConfig } from '@/types/resume'

export function clampTemperature(value: number) {
  const safe = Number.isFinite(value) ? value : 0
  return Math.min(1, Math.max(0, Math.round(safe * 10) / 10))
}

export function clampTopP(value: number) {
  const safe = Number.isFinite(value) ? value : 0
  return Math.min(1, Math.max(0, Math.round(safe * 100) / 100))
}

export function normalizeMaxTokens(value: unknown) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
    return null
  }

  return Math.max(1, Math.round(value))
}

export function createDefaultModelConfig(
  _locale: Locale,
  overrides: Partial<ModelConfig> = {},
): ModelConfig {
  const provider = normalizeProviderId(overrides.provider ?? DEFAULT_MODEL_PROVIDER_ID)

  return {
    id: '',
    provider,
    providerLabel: provider,
    iconProvider: provider,
    providerKind: 'custom',
    apiFamily: 'openai_compatible_chat',
    nickname: '',
    apiKeyPreview: '',
    model: '',
    apiUrl: '',
    temperature: null,
    topP: null,
    maxTokens: null,
    contextWindowTokens: 32768,
    supportsImage: false,
    supportsThinking: false,
    thinkingEnabled: false,
    ...overrides,
  }
}

export function normalizeModelConfig(
  value: unknown,
  locale: Locale,
): ModelConfig | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const raw = value as LegacyModelConfig & Partial<ModelConfig>
  const provider = inferModelProviderId(raw)
  const providerKind = raw.providerKind ?? 'custom'
  const apiFamily = raw.apiFamily ?? 'openai_compatible_chat'
  const temperature =
    typeof raw.temperature === 'number' && Number.isFinite(raw.temperature)
      ? raw.temperature
      : null
  const topP =
    typeof raw.topP === 'number' && Number.isFinite(raw.topP)
      ? raw.topP
      : null

  return createDefaultModelConfig(locale, {
    id: typeof raw.id === 'string' ? raw.id : '',
    providerKind,
    apiFamily,
    nickname:
      typeof raw.nickname === 'string' && raw.nickname.trim()
        ? raw.nickname
        : typeof raw.model === 'string'
          ? raw.model
          : '',
    apiKeyPreview:
      typeof raw.apiKeyPreview === 'string' && raw.apiKeyPreview.trim()
        ? raw.apiKeyPreview.trim()
        : '',
    providerLabel:
      typeof raw.providerLabel === 'string' && raw.providerLabel.trim()
        ? raw.providerLabel.trim()
        : provider,
    iconProvider:
      typeof raw.iconProvider === 'string' && raw.iconProvider.trim()
        ? raw.iconProvider.trim()
        : provider,
    model:
      typeof raw.model === 'string' && raw.model.trim()
        ? raw.model
        : '',
    provider,
    apiUrl:
      typeof raw.apiUrl === 'string' && raw.apiUrl.trim()
        ? raw.apiUrl
        : '',
    temperature: temperature === null ? null : clampTemperature(temperature),
    topP: topP === null ? null : clampTopP(topP),
    maxTokens: normalizeMaxTokens(raw.maxTokens),
    contextWindowTokens: normalizeMaxTokens(raw.contextWindowTokens) ?? 32768,
    supportsImage: Boolean(raw.supportsImage),
    supportsThinking: Boolean(raw.supportsThinking),
    thinkingEnabled: Boolean(raw.thinkingEnabled && raw.supportsThinking),
  })
}

export function normalizeModelConfigs(
  source: { modelConfigs?: unknown; modelConfig?: unknown } | null | undefined,
  locale: Locale,
) {
  if (Array.isArray(source?.modelConfigs)) {
    const normalized = source.modelConfigs
      .map((item) => normalizeModelConfig(item, locale))
      .filter((item): item is ModelConfig => Boolean(item))

    if (normalized.length > 0) {
      return normalized
    }
  }

  const legacy = normalizeModelConfig(source?.modelConfig, locale)

  return legacy ? [legacy] : []
}

export function formatApiKeyPreview(apiKeyPreview: string) {
  const trimmed = apiKeyPreview.trim()

  if (!trimmed) {
    return '—'
  }

  return trimmed
}

export function getModelDisplayName(config: Pick<ModelConfig, 'nickname' | 'model'>) {
  const nickname = config.nickname.trim()
  const model = config.model.trim()

  if (nickname && model && nickname !== model) {
    return `${nickname} (${model})`
  }

  return nickname || model || '—'
}
