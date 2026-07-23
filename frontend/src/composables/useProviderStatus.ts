import { ref } from 'vue'

import { getProviderStatus, type ProviderStatus } from '../api'


export function useProviderStatus() {
  const providerStatus = ref<ProviderStatus | null>(null)

  async function refreshProviderStatus() {
    providerStatus.value = await getProviderStatus()
  }

  return { providerStatus, refreshProviderStatus }
}
