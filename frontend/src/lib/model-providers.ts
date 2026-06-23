export const DEFAULT_MODEL_PROVIDER_ID = 'openai'

export interface ModelProviderMeta {
  id: string
  label: string
  iconProvider: string
  apiUrl: string
  officialUrl: string
  defaultModel: string
  local: boolean
  authRequired: boolean
}

export const MODEL_PROVIDERS: ModelProviderMeta[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    iconProvider: 'openai',
    apiUrl: 'https://api.openai.com/v1',
    officialUrl: 'https://platform.openai.com/docs/api-reference',
    defaultModel: 'gpt-5.1',
    local: false,
    authRequired: true,
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    iconProvider: 'anthropic',
    apiUrl: 'https://api.anthropic.com/v1',
    officialUrl: 'https://docs.anthropic.com/en/api/overview',
    defaultModel: 'claude-sonnet-4.5',
    local: false,
    authRequired: true,
  },
  {
    id: 'google',
    label: 'Google Gemini',
    iconProvider: 'google',
    apiUrl: 'https://generativelanguage.googleapis.com/v1beta',
    officialUrl: 'https://ai.google.dev/gemini-api/docs',
    defaultModel: 'gemini-2.0-flash',
    local: false,
    authRequired: true,
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    iconProvider: 'deepseek',
    apiUrl: 'https://api.deepseek.com',
    officialUrl: 'https://api-docs.deepseek.com',
    defaultModel: 'deepseek-chat',
    local: false,
    authRequired: true,
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    iconProvider: 'openrouter',
    apiUrl: 'https://openrouter.ai/api/v1',
    officialUrl: 'https://openrouter.ai/docs/api-reference/overview',
    defaultModel: 'openai/gpt-4o-mini',
    local: false,
    authRequired: true,
  },
  {
    id: 'ollama',
    label: 'Ollama',
    iconProvider: 'ollama',
    apiUrl: 'http://localhost:11434/v1',
    officialUrl: 'https://ollama.com/blog/openai-compatibility',
    defaultModel: 'llama3.1',
    local: true,
    authRequired: false,
  },
  {
    id: 'vllm',
    label: 'vLLM',
    iconProvider: 'vllm',
    apiUrl: 'http://localhost:8000/v1',
    officialUrl:
      'https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html',
    defaultModel: 'Qwen/Qwen2.5-7B-Instruct',
    local: true,
    authRequired: false,
  },
  {
    id: 'sglang',
    label: 'SGLang',
    iconProvider: 'sglang',
    apiUrl: 'http://localhost:30000/v1',
    officialUrl: 'https://docs.sglang.ai/backend/openai_api_completions.html',
    defaultModel: 'default',
    local: true,
    authRequired: false,
  },
  {
    id: 'lmstudio',
    label: 'LM Studio',
    iconProvider: 'lmstudio',
    apiUrl: 'http://localhost:1234/v1',
    officialUrl: 'https://lmstudio.ai/docs/app/api/endpoints/openai',
    defaultModel: 'local-model',
    local: true,
    authRequired: false,
  },
  {
    id: 'qwen',
    label: 'Qwen',
    iconProvider: 'qwen',
    apiUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    officialUrl:
      'https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope',
    defaultModel: 'qwen-max',
    local: false,
    authRequired: true,
  },
  {
    id: 'zhipuai',
    label: 'Zhipu AI',
    iconProvider: 'zhipuai',
    apiUrl: 'https://open.bigmodel.cn/api/paas/v4',
    officialUrl: 'https://docs.bigmodel.cn/api-reference',
    defaultModel: 'glm-4-plus',
    local: false,
    authRequired: true,
  },
  {
    id: 'moonshotai',
    label: 'Moonshot AI',
    iconProvider: 'moonshotai',
    apiUrl: 'https://api.moonshot.ai/v1',
    officialUrl: 'https://platform.moonshot.ai/docs/api-reference',
    defaultModel: 'moonshot-v1-128k',
    local: false,
    authRequired: true,
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    iconProvider: 'minimax',
    apiUrl: 'https://api.minimax.io/v1',
    officialUrl: 'https://platform.minimax.io/docs',
    defaultModel: 'MiniMax-M3',
    local: false,
    authRequired: true,
  },
  {
    id: 'mistral',
    label: 'Mistral AI',
    iconProvider: 'mistral',
    apiUrl: 'https://api.mistral.ai/v1',
    officialUrl: 'https://docs.mistral.ai/api/',
    defaultModel: 'mistral-large-latest',
    local: false,
    authRequired: true,
  },
  {
    id: 'siliconcloud',
    label: 'SiliconCloud',
    iconProvider: 'siliconcloud',
    apiUrl: 'https://api.siliconflow.cn/v1',
    officialUrl:
      'https://docs.siliconflow.cn/cn/api-reference/chat-completions/chat-completions',
    defaultModel: 'deepseek-ai/DeepSeek-V3',
    local: false,
    authRequired: true,
  },
  {
    id: 'modelscope',
    label: 'ModelScope',
    iconProvider: 'modelscope',
    apiUrl: 'https://api-inference.modelscope.cn/v1',
    officialUrl: 'https://modelscope.cn/docs/model-service/API-Inference/intro',
    defaultModel: 'Qwen/Qwen2.5-72B-Instruct',
    local: false,
    authRequired: true,
  },
  {
    id: 'cloudflare-workers-ai',
    label: 'Cloudflare Workers AI',
    iconProvider: 'cloudflare-workers-ai',
    apiUrl: 'https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1',
    officialUrl:
      'https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/',
    defaultModel: '@cf/meta/llama-3.1-8b-instruct',
    local: false,
    authRequired: true,
  },
  {
    id: 'perplexity',
    label: 'Perplexity',
    iconProvider: 'perplexity',
    apiUrl: 'https://api.perplexity.ai',
    officialUrl: 'https://docs.perplexity.ai/api-reference',
    defaultModel: 'sonar-pro',
    local: false,
    authRequired: true,
  },
  {
    id: 'xai',
    label: 'xAI',
    iconProvider: 'xai',
    apiUrl: 'https://api.x.ai/v1',
    officialUrl: 'https://docs.x.ai/docs/api-reference',
    defaultModel: 'grok-3',
    local: false,
    authRequired: true,
  },
  {
    id: 'azure',
    label: 'Azure OpenAI',
    iconProvider: 'azure',
    apiUrl: 'https://{resource}.openai.azure.com/openai',
    officialUrl: 'https://learn.microsoft.com/en-us/azure/ai-foundry/openai/reference',
    defaultModel: 'gpt-4o',
    local: false,
    authRequired: true,
  },
  {
    id: 'bedrock',
    label: 'AWS Bedrock',
    iconProvider: 'amazon-bedrock',
    apiUrl: 'https://bedrock-runtime.{region}.amazonaws.com',
    officialUrl: 'https://docs.aws.amazon.com/bedrock/latest/APIReference/welcome.html',
    defaultModel: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
    local: false,
    authRequired: true,
  },
]

const PROVIDERS_BY_ID = new Map(MODEL_PROVIDERS.map((item) => [item.id, item]))

const PROVIDER_ALIASES: Record<string, string> = {
  'amazon-bedrock': 'bedrock',
  alibaba: 'qwen',
  anthropic: 'anthropic',
  azure: 'azure',
  bedrock: 'bedrock',
  claude: 'anthropic',
  cloudflare: 'cloudflare-workers-ai',
  'cloudflare-workers-ai': 'cloudflare-workers-ai',
  dashscope: 'qwen',
  deepseek: 'deepseek',
  gemini: 'google',
  google: 'google',
  lmstudio: 'lmstudio',
  modelscope: 'modelscope',
  moonshot: 'moonshotai',
  moonshotai: 'moonshotai',
  minimax: 'minimax',
  mistral: 'mistral',
  ollama: 'ollama',
  openai: 'openai',
  openrouter: 'openrouter',
  perplexity: 'perplexity',
  qwen: 'qwen',
  sglang: 'sglang',
  siliconcloud: 'siliconcloud',
  siliconflow: 'siliconcloud',
  vllm: 'vllm',
  xai: 'xai',
  zhipu: 'zhipuai',
  zhipuai: 'zhipuai',
}

export function getModelProviderMeta(provider?: string) {
  const normalized = provider?.trim().toLowerCase()
  const providerId = normalized
    ? PROVIDER_ALIASES[normalized] ?? normalized
    : DEFAULT_MODEL_PROVIDER_ID

  return PROVIDERS_BY_ID.get(providerId) ?? PROVIDERS_BY_ID.get(DEFAULT_MODEL_PROVIDER_ID)!
}

export function getProviderApiUrl(provider?: string) {
  return getModelProviderMeta(provider).apiUrl
}

export function getProviderDefaultModel(provider?: string) {
  return getModelProviderMeta(provider).defaultModel
}

export function isProviderApiKeyRequired(provider?: string) {
  return getModelProviderMeta(provider).authRequired
}

export function inferModelProviderId(source: {
  provider?: string
  apiUrl?: string
  model?: string
  nickname?: string
}) {
  const declared = source.provider?.trim().toLowerCase()

  if (declared) {
    return getModelProviderMeta(declared).id
  }

  const apiUrl = source.apiUrl?.toLowerCase() ?? ''
  const modelText = `${source.nickname ?? ''} ${source.model ?? ''}`.toLowerCase()
  const combined = `${apiUrl} ${modelText}`

  if (combined.includes('openrouter')) return 'openrouter'
  if (combined.includes('ollama') || apiUrl.includes(':11434')) return 'ollama'
  if (combined.includes('sglang') || apiUrl.includes(':30000')) return 'sglang'
  if (combined.includes('vllm') || apiUrl.includes(':8000')) return 'vllm'
  if (combined.includes('lmstudio') || apiUrl.includes(':1234')) return 'lmstudio'
  if (combined.includes('anthropic') || combined.includes('claude')) return 'anthropic'
  if (combined.includes('google') || combined.includes('gemini')) return 'google'
  if (combined.includes('azure')) return 'azure'
  if (combined.includes('bedrock') || combined.includes('amazon')) return 'bedrock'
  if (combined.includes('deepseek')) return 'deepseek'
  if (combined.includes('dashscope') || combined.includes('qwen')) return 'qwen'
  if (combined.includes('zhipu') || combined.includes('glm')) return 'zhipuai'
  if (combined.includes('moonshot') || combined.includes('kimi')) return 'moonshotai'
  if (combined.includes('minimax')) return 'minimax'
  if (combined.includes('mistral') || combined.includes('codestral')) return 'mistral'
  if (combined.includes('siliconcloud') || combined.includes('siliconflow')) {
    return 'siliconcloud'
  }
  if (combined.includes('modelscope')) return 'modelscope'
  if (combined.includes('cloudflare')) return 'cloudflare-workers-ai'
  if (combined.includes('perplexity') || combined.includes('sonar')) return 'perplexity'
  if (combined.includes('x.ai') || combined.includes('grok')) return 'xai'

  return DEFAULT_MODEL_PROVIDER_ID
}
