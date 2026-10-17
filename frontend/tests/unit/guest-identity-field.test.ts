import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import GuestIdentityField from '@/components/guest/GuestIdentityField.vue'

type Props = InstanceType<typeof GuestIdentityField>['$props']

function mountField(props: Partial<Props> = {}) {
  return mount(GuestIdentityField, { global: { plugins: [Quasar] }, props: { label: 'USERNAME', modelValue: '', ...props } })
}

const randomButton = (wrapper: ReturnType<typeof mountField>) => wrapper.get('button.identity-field__random')

describe('GuestIdentityField', () => {
  it('shows that a blank value is chosen at build time', () => {
    const wrapper = mountField()
    expect(wrapper.get('input').attributes('placeholder')).toBe('chosen at build time')
  })

  it('shows another placeholder when the parent gives one', () => {
    expect(mountField({ placeholder: 'chosen at clone time' }).get('input').attributes('placeholder')).toBe('chosen at clone time')
  })

  it('emits what is typed', async () => {
    const wrapper = mountField()
    await wrapper.get('input').setValue('Marta')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['Marta'])
  })

  it('clears the value when RANDOM is pressed', async () => {
    const wrapper = mountField({ modelValue: 'Marta' })
    await randomButton(wrapper).trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([''])
  })

  it('marks RANDOM as on while the value is blank and off once something is typed', async () => {
    const wrapper = mountField()
    expect(randomButton(wrapper).attributes('aria-pressed')).toBe('true')
    await wrapper.setProps({ modelValue: 'Marta' })
    expect(randomButton(wrapper).attributes('aria-pressed')).toBe('false')
  })

  it('shows the error and the hint', () => {
    const wrapper = mountField({ error: 'Username must match [A-Za-z]+', hint: 'A realistic first name when left blank' })
    expect(wrapper.text()).toContain('Username must match [A-Za-z]+')
    expect(wrapper.get('.identity-field__hint').text()).toBe('A realistic first name when left blank')
  })

  it('masks a secret and can reveal it', async () => {
    const wrapper = mountField({ secret: true, modelValue: 'q7Zp-Lm2x' })
    expect(wrapper.get('input').attributes('type')).toBe('password')
    await wrapper.get('button[aria-label="Show"]').trigger('click')
    expect(wrapper.get('input').attributes('type')).toBe('text')
  })

  describe('read-only', () => {
    it('shows the value, gives the reason and offers no RANDOM', () => {
      const wrapper = mountField({ readonly: true, modelValue: 'Marta', reason: 'a different username needs a build' })
      expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Marta')
      expect(wrapper.get('input').attributes('disabled')).toBeDefined()
      expect(wrapper.get('.identity-field__hint').text()).toBe('a different username needs a build')
      expect(wrapper.find('button.identity-field__random').exists()).toBe(false)
    })
  })
})
