import type { Locale } from '@/i18n'
import {
  DEFAULT_MODEL_PROVIDER_ID,
  getProviderApiUrl,
  getProviderDefaultModel,
  inferModelProviderId,
} from '@/lib/model-providers'
import { createId } from '@/lib/resume'
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

function getDefaultSystemPrompt(locale: Locale) {
  return locale === 'zh'
    ? '你是 ResuMate 的简历优化助手。输出应简洁、结构化，并优先强化经历中的结果与关键词覆盖。'
    : "You are ResuMate's resume copilot. Keep suggestions concise, structured, and biased toward quantified impact plus stronger keyword coverage."
}

export function createDefaultModelConfig(
  locale: Locale,
  overrides: Partial<ModelConfig> = {},
): ModelConfig {
  const provider = overrides.provider ?? DEFAULT_MODEL_PROVIDER_ID

  return {
    id: createId('llm'),
    provider,
    nickname: '',
    apiKeyPreview: '',
    model: getProviderDefaultModel(provider),
    apiUrl: getProviderApiUrl(provider),
    temperature: 0.4,
    topP: 0.9,
    maxTokens: null,
    systemPrompt: getDefaultSystemPrompt(locale),
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
  const temperature =
    typeof raw.temperature === 'number' && Number.isFinite(raw.temperature)
      ? raw.temperature
      : 0.4
  const topP =
    typeof raw.topP === 'number' && Number.isFinite(raw.topP)
      ? raw.topP
      : 0.9

  return createDefaultModelConfig(locale, {
    id: typeof raw.id === 'string' ? raw.id : createId('llm'),
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
    model:
      typeof raw.model === 'string' && raw.model.trim()
        ? raw.model
        : getProviderDefaultModel(provider),
    provider,
    apiUrl:
      typeof raw.apiUrl === 'string' && raw.apiUrl.trim()
        ? raw.apiUrl
        : getProviderApiUrl(provider),
    temperature: clampTemperature(temperature),
    topP: clampTopP(topP),
    maxTokens: normalizeMaxTokens(raw.maxTokens),
    systemPrompt:
      typeof raw.systemPrompt === 'string' && raw.systemPrompt.trim()
        ? raw.systemPrompt
        : getDefaultSystemPrompt(locale),
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
