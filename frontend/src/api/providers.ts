import { apiRequest } from './client'
import type { ProviderStatus, RequestOptions } from './types'


export function getProviderStatus(options: RequestOptions = {}): Promise<ProviderStatus> {
  return apiRequest('/api/providers/status', {}, options)
}
