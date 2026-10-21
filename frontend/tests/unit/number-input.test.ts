import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import NumberInput from '@/components/NumberInput.vue'

type Props = { modelValue: string | number; min?: number; max?: number; step?: number; disable?: boolean }

function mountInput(props: Props) {
  return mount(NumberInput, { global: { plugins: [Quasar] }, props: { label: 'Timeout', ...props } })
}

const emitted = (wrapper: ReturnType<typeof mountInput>) => wrapper.emitted('update:modelValue')?.at(-1)?.[0]

describe('NumberInput', () => {
  it('renders a number input carrying the label', () => {
    const wrapper = mountInput({ modelValue: 5 })
    expect(wrapper.find('input').attributes('type')).toBe('number')
    expect(wrapper.text()).toContain('Timeout')
  })

  it('steps up and down by one from the current value', async () => {
    const wrapper = mountInput({ modelValue: 50 })
    await wrapper.find('[aria-label="Increase"]').trigger('click')
    expect(emitted(wrapper)).toBe('51')
    await wrapper.find('[aria-label="Decrease"]').trigger('click')
    expect(emitted(wrapper)).toBe('49')
  })

  it('steps by the given step', async () => {
    const wrapper = mountInput({ modelValue: 10, step: 5 })
    await wrapper.find('[aria-label="Increase"]').trigger('click')
    expect(emitted(wrapper)).toBe('15')
  })

  it('starts from the minimum when the field is empty', async () => {
    const wrapper = mountInput({ modelValue: '', min: 1 })
    await wrapper.find('[aria-label="Increase"]').trigger('click')
    expect(emitted(wrapper)).toBe('1')
  })

  it('does not step past the minimum or the maximum', async () => {
    const wrapper = mountInput({ modelValue: 1, min: 1, max: 1 })
    await wrapper.find('[aria-label="Decrease"]').trigger('click')
    expect(emitted(wrapper)).toBe('1')
    await wrapper.find('[aria-label="Increase"]').trigger('click')
    expect(emitted(wrapper)).toBe('1')
  })

  it('cannot be stepped while disabled', async () => {
    const wrapper = mountInput({ modelValue: 5, disable: true })
    await wrapper.find('[aria-label="Increase"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})
