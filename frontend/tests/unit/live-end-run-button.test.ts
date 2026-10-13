import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import LiveEndRunButton from '@/components/LiveEndRunButton.vue'
import type { EndRunPhase } from '@/services/end-run'

function mountButton(phase: EndRunPhase, label = 'END RUN', title = 'why') {
  return mount(LiveEndRunButton, { global: { plugins: [Quasar] }, props: { phase, label, title } })
}

const button = (wrapper: ReturnType<typeof mountButton>) => wrapper.find('[data-live="end-run"]')

describe('LiveEndRunButton', () => {
  it('renders nothing while hidden', () => {
    expect(button(mountButton('hidden')).exists()).toBe(false)
  })

  it('is enabled and says END RUN when ready, and asks to end the run when clicked', async () => {
    const wrapper = mountButton('ready')
    expect(button(wrapper).text()).toContain('END RUN')
    expect(button(wrapper).attributes('disabled')).toBeUndefined()
    await button(wrapper).trigger('click')
    expect(wrapper.emitted('press')).toHaveLength(1)
  })

  it.each(['waiting', 'confirming', 'ending'] as const)('is disabled while %s', (phase) => {
    expect(button(mountButton(phase)).attributes('disabled')).toBeDefined()
  })

  it('shows the label it is given', () => {
    expect(button(mountButton('ending', 'ENDING...')).text()).toContain('ENDING...')
  })

  it('carries the explanation as a title on its wrapper, which shows even when the button is disabled', () => {
    const wrapper = mountButton('waiting', 'END RUN', 'The analysis has not started in the guest yet.')
    expect(wrapper.attributes('title')).toBe('The analysis has not started in the guest yet.')
  })
})
