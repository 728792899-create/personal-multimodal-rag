import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useSourceSync } from './useSourceSync'

const api = vi.hoisted(() => ({
  listSources: vi.fn(),
  listSyncRuns: vi.fn(),
  createSource: vi.fn(),
  deleteSource: vi.fn(),
  syncSource: vi.fn(),
  confirmSourceDeletions: vi.fn(),
}))

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  ...api,
}))

describe('useSourceSync', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listSources.mockResolvedValue({
      sources: [],
      capabilities: { types: ['url_list'], directory_roots: [] },
    })
    api.listSyncRuns.mockResolvedValue([])
  })

  it('creates a source and refreshes the selected knowledge base', async () => {
    api.createSource.mockResolvedValue({ id: 'source-1' })
    const state = useSourceSync()

    await state.add(
      'url_list',
      'Docs',
      'default',
      { urls: ['https://example.com'] },
    )

    expect(api.createSource).toHaveBeenCalledWith({
      type: 'url_list',
      name: 'Docs',
      knowledge_base_id: 'default',
      config: { urls: ['https://example.com'] },
    })
    expect(api.listSources).toHaveBeenCalledWith('default')
  })

  it('retains a readable error when refresh fails', async () => {
    api.listSources.mockRejectedValue(new Error('source service unavailable'))
    const state = useSourceSync()

    await state.refresh('default')

    expect(state.error.value).toBe('source service unavailable')
    expect(state.loading.value).toBe(false)
  })
})
