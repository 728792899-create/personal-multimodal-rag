import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import LoginPage from './LoginPage.vue'


describe('LoginPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('submits the password without persisting it in browser storage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const wrapper = mount(LoginPage, {
      props: { submitting: false, error: '' },
    })

    await wrapper.get('input[type="password"]').setValue('correct horse battery staple')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('submit')?.[0]).toEqual(['correct horse battery staple'])
    expect(setItem).not.toHaveBeenCalled()
  })

  it('announces authentication failures', () => {
    const wrapper = mount(LoginPage, {
      props: { submitting: false, error: 'Invalid administrator credentials' },
    })
    expect(wrapper.get('[role="alert"]').text()).toContain('Invalid')
  })
})
