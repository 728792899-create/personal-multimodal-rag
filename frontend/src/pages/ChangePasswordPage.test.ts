import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChangePasswordPage from './ChangePasswordPage.vue'


describe('ChangePasswordPage', () => {
  it('仅在新密码符合长度且两次一致时提交', async () => {
    const wrapper = mount(ChangePasswordPage, {
      props: { username: 'reader', submitting: false, error: '' },
    })

    await wrapper.get('#current-password').setValue('temporary reader password')
    await wrapper.get('#new-password').setValue('new password')
    await wrapper.get('#confirm-password').setValue('different password')
    expect(wrapper.get('[role="alert"]').text()).toContain('不一致')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()

    await wrapper.get('#new-password').setValue('permanent reader password')
    await wrapper.get('#confirm-password').setValue('permanent reader password')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual([
      'temporary reader password',
      'permanent reader password',
    ])
  })
})
