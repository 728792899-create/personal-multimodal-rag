import { apiRequest } from './client'
import type { RealUsageSummary, RequestOptions } from './types'


export function getRealUsageSummary(options: RequestOptions = {}): Promise<RealUsageSummary> {
  return apiRequest('/api/system/usage-evidence', {}, options)
}
