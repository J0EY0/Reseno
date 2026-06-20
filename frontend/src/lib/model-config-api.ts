import { apiRoutes, requestApi } from '@/lib/api-client'
import type { ModelConfig } from '@/types/resume'

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
