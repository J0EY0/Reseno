import type { ModelConfig } from '@/types/resume'

export const DEFAULT_MODEL_PROVIDER_ID = 'openai'

export type ModelProviderKind = ModelConfig['providerKind']
export type ModelApiFamily = ModelConfig['apiFamily']

export interface ModelProviderMeta {
  id: string
  label: string
  kind: ModelProviderKind
  apiFamily: ModelApiFamily | null
  iconProvider: string
  defaultBaseUrl: string
  officialUrl: string
  authRequired: boolean
  supportsModelDiscovery: boolean
  supportsCustomCapabilities: boolean
}

const PROVIDER_ALIASES: Record<string, string> = {
  alibaba: 'qwen',
  anthropic: 'anthropic',
  claude: 'anthropic',
  dashscope: 'qwen',
  deepseek: 'deepseek',
  gemini: 'google',
  glm: 'glm',
  google: 'google',
  kimi: 'moonshot',
  local: 'ollama',
  minimax: 'minimax',
  moonshot: 'moonshot',
  moonshotai: 'moonshot',
  ollama: 'ollama',
  ollma: 'ollama',
  openai: 'openai',
  qwen: 'qwen',
  sglang: 'sglang',
  vllm: 'vllm',
  xai: 'xai',
  'z.ai': 'glm',
  zai: 'glm',
  zhipu: 'glm',
  zhipuai: 'glm',
}

export function normalizeProviderId(provider?: string) {
  const normalized = provider?.trim().toLowerCase()

  if (!normalized) {
    return DEFAULT_MODEL_PROVIDER_ID
  }

  return PROVIDER_ALIASES[normalized] ?? normalized
}

export function inferModelProviderId(source: {
  provider?: string
  apiUrl?: string
  model?: string
  nickname?: string
}) {
  if (source.provider?.trim()) {
    return normalizeProviderId(source.provider)
  }

  const apiUrl = source.apiUrl?.toLowerCase() ?? ''
  const modelText = `${source.nickname ?? ''} ${source.model ?? ''}`.toLowerCase()
  const combined = `${apiUrl} ${modelText}`

  if (combined.includes('anthropic') || combined.includes('claude')) {
    return 'anthropic'
  }
  if (combined.includes('google') || combined.includes('gemini')) return 'google'
  if (combined.includes('deepseek')) return 'deepseek'
  if (combined.includes('dashscope') || combined.includes('qwen')) return 'qwen'
  if (
    combined.includes('z.ai') ||
    combined.includes('zhipu') ||
    combined.includes('bigmodel') ||
    combined.includes('glm')
  ) {
    return 'glm'
  }
  if (combined.includes('minimax')) return 'minimax'
  if (combined.includes('moonshot') || combined.includes('kimi')) return 'moonshot'
  if (combined.includes('x.ai') || combined.includes('grok')) return 'xai'
  if (combined.includes('ollama') || apiUrl.includes(':11434')) return 'ollama'
  if (combined.includes('vllm') || apiUrl.includes(':8000')) return 'vllm'
  if (combined.includes('sglang') || apiUrl.includes(':30000')) return 'sglang'
  if (
    combined.includes('localhost') ||
    apiUrl.includes(':1234')
  ) {
    return 'ollama'
  }

  return DEFAULT_MODEL_PROVIDER_ID
}
