import type { Locale } from '@/i18n'
import type { ModelConfig, ThinkingMode } from '@/types/resume'

export const DEFAULT_MODEL_API_FAMILY = 'openai_compatible_chat'
export const DEFAULT_CONTEXT_WINDOW_TOKENS = 32768

/**
 * Normalize provider capability metadata into the only two product-level modes.
 * Auto is always present because it delegates behavior to the provider; Off is
 * retained only when discovery explicitly guarantees a true no-reasoning mode.
 */
export function normalizeAvailableThinkingModes(
  value: unknown,
): ThinkingMode[] {
  return Array.isArray(value) && value.includes('off')
    ? ['auto', 'off']
    : ['auto']
}

/**
 * Resolve the persisted preference against the current model capability. This
 * keeps a stale Off preference from reaching the save API after the user moves
 * to a model that cannot guarantee disabled reasoning.
 */
export function resolveThinkingMode(
  value: unknown,
  availableModes: readonly ThinkingMode[],
): ThinkingMode {
  return value === 'off' && availableModes.includes('off') ? 'off' : 'auto'
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
  const provider =
    typeof overrides.provider === 'string' ? overrides.provider.trim() : ''

  return {
    id: '',
    provider,
    providerLabel: provider,
    iconProvider: provider,
    providerKind: 'custom',
    apiFamily: DEFAULT_MODEL_API_FAMILY,
    nickname: '',
    apiKeyPreview: '',
    model: '',
    apiUrl: '',
    temperature: null,
    topP: null,
    maxTokens: null,
    contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
    supportsImage: false,
    supportsThinking: false,
    thinkingMode: 'auto',
    availableThinkingModes: ['auto'],
    supportsTools: true,
    supportsStreaming: true,
    ...overrides,
  }
}

function normalizeModelConfig(
  value: unknown,
  locale: Locale,
): ModelConfig | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const raw = value as Partial<ModelConfig>
  const provider = typeof raw.provider === 'string' ? raw.provider.trim() : ''
  const providerKind = raw.providerKind ?? 'custom'
  const apiFamily = raw.apiFamily ?? DEFAULT_MODEL_API_FAMILY
  const temperature =
    typeof raw.temperature === 'number' && Number.isFinite(raw.temperature)
      ? raw.temperature
      : null
  const topP =
    typeof raw.topP === 'number' && Number.isFinite(raw.topP)
      ? raw.topP
      : null
  const availableThinkingModes = normalizeAvailableThinkingModes(
    raw.availableThinkingModes,
  )

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
    temperature,
    topP,
    maxTokens: normalizeMaxTokens(raw.maxTokens),
    contextWindowTokens:
      normalizeMaxTokens(raw.contextWindowTokens) ?? DEFAULT_CONTEXT_WINDOW_TOKENS,
    supportsImage: Boolean(raw.supportsImage),
    supportsThinking: Boolean(raw.supportsThinking),
    thinkingMode: resolveThinkingMode(
      raw.thinkingMode,
      availableThinkingModes,
    ),
    availableThinkingModes,
    supportsTools: raw.supportsTools !== false,
    supportsStreaming: raw.supportsStreaming !== false,
  })
}

export function normalizeModelConfigs(
  source: { modelConfigs?: unknown } | null | undefined,
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

  return []
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
