import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import LiveExtendButton from '@/components/LiveExtendButton.vue'

const TITLE = 'Adds 60 seconds to the run'

function mountButton(props: { visible?: boolean; disabled?: boolean; title?: string } = {}) {
  return mount(LiveExtendButton, {
    global: { plugins: [Quasar] },
    props: { visible: true, disabled: false, title: TITLE, ...props },
  })
}

const button = (wrapper: ReturnType<typeof mountButton>) => wrapper.find('[data-live="extend-run"]')

describe('LiveExtendButton', () => {
  it('renders nothing when it is not visible', () => {
    expect(button(mountButton({ visible: false })).exists()).toBe(false)
  })

  it('says +60S and asks to extend the run when clicked', async () => {
    const wrapper = mountButton()
    expect(button(wrapper).text()).toContain('+60S')
    expect(button(wrapper).attributes('disabled')).toBeUndefined()
    await button(wrapper).trigger('click')
    expect(wrapper.emitted('press')).toHaveLength(1)
  })

  it('is disabled while disabled is set', () => {
    expect(button(mountButton({ disabled: true })).attributes('disabled')).toBeDefined()
  })

  it('carries the explanation as a title on its wrapper, which shows even when the button is disabled', () => {
    const wrapper = mountButton({ disabled: true, title: 'The run is already at its longest (20 minutes)' })
    expect(wrapper.attributes('title')).toBe('The run is already at its longest (20 minutes)')
  })
})
