import type { ModelConfig } from '@/types/resume'

type ModelProviderKind = ModelConfig['providerKind']
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
  supportsTools: boolean
  supportsStreaming: boolean
}
