import { apiRoutes, requestApi } from '@/lib/api-client'
import type { ModelApiFamily, ModelProviderMeta } from '@/lib/model-providers'
import type { ModelConfig } from '@/types/resume'

export interface DiscoveredModel {
  id: string
  label: string
  contextWindowTokens: number
  maxOutputTokens: number | null
  supportsImage: boolean
  supportsThinking: boolean
  supportsTools: boolean
  supportsStreaming: boolean
  metadataSource: string
}

interface ModelProvidersResponse {
  providers: ModelProviderMeta[]
}

let modelProvidersRequest: Promise<ModelProvidersResponse> | null = null

export function getModelProviders() {
  if (!modelProvidersRequest) {
    // Provider metadata is shared by every create/edit dialog. Reusing the
    // request prevents concurrently opened forms from issuing the same call.
    modelProvidersRequest = requestApi<ModelProvidersResponse>(
      apiRoutes.modelProviders,
      { notifyOnError: false },
    ).catch((error) => {
      modelProvidersRequest = null
      throw error
    })
  }

  return modelProvidersRequest
}

export async function discoverModels(input: {
  provider: string
  apiFamily?: ModelApiFamily | null
  apiUrl: string
  apiKey?: string
  configId?: string
  refresh?: boolean
}) {
  return requestApi<{ models: DiscoveredModel[]; source: 'cache' | 'provider' }>(
    apiRoutes.modelProviderDiscovery,
    {
      method: 'POST',
      body: input,
    },
  )
}

export async function saveModelConfig(
  config: Omit<ModelConfig, 'id'> & { id?: string },
  apiKey?: string,
) {
  return requestApi<ModelConfig>(apiRoutes.modelConfigs, {
    method: 'POST',
    body: {
      ...config,
      ...(apiKey ? { apiKey } : {}),
    },
  })
}

export async function deleteModelConfig(id: string) {
  return requestApi<{ id: string }>(
    `${apiRoutes.modelConfigs}/${encodeURIComponent(id)}`,
    {
      method: 'DELETE',
    },
  )
}
