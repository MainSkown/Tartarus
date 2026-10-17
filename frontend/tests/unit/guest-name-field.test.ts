import { mount } from '@vue/test-utils'
import { Quasar, QInput } from 'quasar'
import { describe, expect, it } from 'vitest'
import GuestNameField from '@/components/guest/GuestNameField.vue'

function mountField(props: { modelValue?: string; error?: string; label?: string } = {}) {
  return mount(GuestNameField, { global: { plugins: [Quasar] }, props: { modelValue: '', ...props } })
}

describe('GuestNameField', () => {
  it('explains that only Tartarus sees the name', () => {
    expect(mountField().text()).toContain('Only Tartarus sees this name; Windows never does.')
  })

  it('emits what is typed', async () => {
    const wrapper = mountField()
    await wrapper.get('input').setValue('lab5')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['lab5'])
  })

  it('shows the error on the input', () => {
    const input = mountField({ error: 'Another guest is already called lab1' }).getComponent(QInput)
    expect(input.props('error')).toBe(true)
    expect(input.props('errorMessage')).toBe('Another guest is already called lab1')
  })

  it('takes its label from the parent so the clone form can call it NEW NAME', () => {
    expect(mountField({ label: 'NEW NAME' }).getComponent(QInput).props('label')).toBe('NEW NAME')
  })
})
