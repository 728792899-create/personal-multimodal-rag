import { apiRequest, jsonBody } from './client'
import type {
  DeepSeekRuntimeMutation,
  ProviderStatus,
  RequestOptions,
} from './types'


export function getProviderStatus(options: RequestOptions = {}): Promise<ProviderStatus> {
  return apiRequest('/api/providers/status', {}, options)
}

export function connectDeepSeekRuntime(
  apiKey: string,
  options: RequestOptions = {},
): Promise<DeepSeekRuntimeMutation> {
  return apiRequest(
    '/api/providers/deepseek/runtime',
    {
      method: 'POST',
      ...jsonBody({ api_key: apiKey }),
    },
    options,
  )
}

export function clearDeepSeekRuntime(
  options: RequestOptions = {},
): Promise<DeepSeekRuntimeMutation> {
  return apiRequest(
    '/api/providers/deepseek/runtime',
    { method: 'DELETE' },
    options,
  )
}
