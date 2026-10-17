import { mount } from '@vue/test-utils'
import { Quasar, QInput, QSelect, QToggle } from 'quasar'
import { describe, expect, it } from 'vitest'
import ProfileOptionField from '@/components/guest/ProfileOptionField.vue'
import type { ProfileOption } from '@/api'
import { DEFENDER_OPTION, HOSTNAME_OPTION, KEY_OPTION, KEYBOARD_OPTION } from './guest-wizard-fixtures'

type Props = InstanceType<typeof ProfileOptionField>['$props']

function mountField(option: ProfileOption, modelValue: unknown, props: Partial<Props> = {}) {
  return mount(ProfileOptionField, { global: { plugins: [Quasar] }, props: { option, modelValue, ...props } })
}

describe('a bool option', () => {
  it('is a toggle labelled with the option and showing its value', () => {
    const wrapper = mountField(DEFENDER_OPTION, true)
    const toggle = wrapper.getComponent(QToggle)
    expect(toggle.props('modelValue')).toBe(true)
    expect(wrapper.text()).toContain('Microsoft Defender')
  })

  it('emits the new value when toggled', () => {
    const wrapper = mountField(DEFENDER_OPTION, true)
    wrapper.getComponent(QToggle).vm.$emit('update:modelValue', false)
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })
})

describe('a string option', () => {
  const OPTION: ProfileOption = { key: 'banner', label: 'Login banner', type: 'string', default: '', help: 'Shown before login.' }

  it('is a text input holding the value', () => {
    const input = mountField(OPTION, 'welcome').getComponent(QInput)
    expect(input.props('modelValue')).toBe('welcome')
    expect(input.props('type')).toBe('text')
  })

  it('emits what is typed', async () => {
    const wrapper = mountField(OPTION, '')
    await wrapper.get('input').setValue('hello')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['hello'])
  })
})

describe('a choice option', () => {
  it('is a select over the choices', () => {
    const select = mountField(KEYBOARD_OPTION, 'US').getComponent(QSelect)
    expect(select.props('options')).toEqual(['Polish (Programmers)', 'US', 'German'])
    expect(select.props('modelValue')).toBe('US')
  })

  it('emits the chosen value', () => {
    const wrapper = mountField(KEYBOARD_OPTION, 'US')
    wrapper.getComponent(QSelect).vm.$emit('update:modelValue', 'German')
    expect(wrapper.emitted('update:modelValue')).toEqual([['German']])
  })
})

describe('a secret option', () => {
  it('is a masked input that can be revealed', async () => {
    const wrapper = mountField(KEY_OPTION, 'AAAAA-BBBBB-CCCCC-DDDDD-EEEEE')
    expect(wrapper.get('input').attributes('type')).toBe('password')
    await wrapper.get('button[aria-label="Show"]').trigger('click')
    expect(wrapper.get('input').attributes('type')).toBe('text')
  })

  it('emits what is typed', async () => {
    const wrapper = mountField(KEY_OPTION, '')
    await wrapper.get('input').setValue('X')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['X'])
  })
})

describe('every option', () => {
  it.each([DEFENDER_OPTION, KEYBOARD_OPTION, KEY_OPTION])('shows its help text beside the control: $key', (option) => {
    expect(mountField(option, option.default).get('.option-field__help').text()).toBe(option.help)
  })

  it('has no help line when the profile gave none', () => {
    expect(mountField({ ...DEFENDER_OPTION, help: undefined }, true).find('.option-field__help').exists()).toBe(false)
  })

  it('notes that it may ask for one manual step only when the profile says so', () => {
    expect(mountField(HOSTNAME_OPTION, 'x').text()).toContain('may ask for one manual step')
    expect(mountField(DEFENDER_OPTION, true).text()).not.toContain('manual step')
  })

  it('shows the error under the control', () => {
    const wrapper = mountField(KEYBOARD_OPTION, 'US', { error: 'must be one of US' })
    expect(wrapper.get('[role="alert"]').text()).toBe('must be one of US')
  })
})

describe('a locked option', () => {
  it.each([DEFENDER_OPTION, KEYBOARD_OPTION, KEY_OPTION])('is greyed and cannot be changed: $key', (option) => {
    const wrapper = mountField(option, option.default, { locked: true })
    expect(wrapper.classes()).toContain('option-field--locked')
    const controls = [QToggle, QSelect, QInput].flatMap((component) => wrapper.findAllComponents(component))
    expect(controls.length).toBeGreaterThan(0)
    expect(controls.every((control) => control.props('disable') === true)).toBe(true)
  })

  it('says why, when given a reason', () => {
    const wrapper = mountField(DEFENDER_OPTION, true, { locked: true, lockedReason: 'inherited from lab1' })
    expect(wrapper.get('.option-field__reason').text()).toBe('inherited from lab1')
  })
})
