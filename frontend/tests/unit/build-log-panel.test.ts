import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import BuildLogPanel from '@/components/guest/BuildLogPanel.vue'

const LINES = ['preflight: media ok', 'guest: agent answered on 8000', 'install: copying files']

const mountPanel = (lines: string[] = LINES) => mount(BuildLogPanel, { attachTo: document.body, global: { plugins: [Quasar] }, props: { lines } })
const body = (wrapper: ReturnType<typeof mountPanel>) => wrapper.find('[data-build="log-body"]')
const followButton = (wrapper: ReturnType<typeof mountPanel>) => wrapper.find('[data-build="follow"]')

function scrollable(element: Element, { scrollHeight, clientHeight }: { scrollHeight: number; clientHeight: number }) {
  Object.defineProperty(element, 'scrollHeight', { value: scrollHeight, configurable: true })
  Object.defineProperty(element, 'clientHeight', { value: clientHeight, configurable: true })
}

describe('BuildLogPanel', () => {
  it('shows every line it was given, one per row, in a mono code block', () => {
    const wrapper = mountPanel()
    expect(body(wrapper).element.tagName).toBe('PRE')
    expect(wrapper.findAll('.build-log__line').map((line) => line.text())).toEqual(LINES)
  })

  it('dims the lines the guest wrote and nothing else', () => {
    const wrapper = mountPanel()
    expect(wrapper.findAll('.build-log__line').map((line) => line.classes().includes('build-log__line--guest'))).toEqual([false, true, false])
  })

  it('says there is no output yet instead of showing an empty box', () => {
    const wrapper = mountPanel([])
    expect(wrapper.text()).toContain('> no output yet')
    expect(wrapper.find('.build-log__line').exists()).toBe(false)
  })

  it('has its title and its two buttons in the one shared panel header', () => {
    const wrapper = mountPanel()
    const header = wrapper.find('.pane-heading')
    expect(header.find('.pane-heading__title').text()).toBe('BUILD LOG')
    expect(header.find('.pane-heading__actions').findAll('button').map((button) => button.text())).toEqual([expect.stringContaining('[PAUSE FOLLOW]'), expect.stringContaining('[COPY LOG]')])
  })

  it('has a COPY LOG button that copies all the lines', () => {
    const wrapper = mountPanel()
    const copy = wrapper.findComponent({ name: 'CopyButton' })
    expect(copy.props()).toMatchObject({ text: LINES.join('\n'), label: '[COPY LOG]' })
  })

  describe('following', () => {
    it('follows from the start, and offers to pause', () => {
      const wrapper = mountPanel()
      expect(followButton(wrapper).text()).toBe('[PAUSE FOLLOW]')
      expect(followButton(wrapper).attributes('aria-pressed')).toBe('true')
    })

    it('starts at the newest line when it opens on a long log', () => {
      const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight')
      Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { value: 900, configurable: true })
      try {
        const wrapper = mountPanel()
        expect(body(wrapper).element.scrollTop).toBe(900)
      } finally {
        if (original) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', original)
        else delete (HTMLElement.prototype as { scrollHeight?: number }).scrollHeight
      }
    })

    it('scrolls to the newest line when lines arrive while following', async () => {
      const wrapper = mountPanel()
      scrollable(body(wrapper).element, { scrollHeight: 900, clientHeight: 200 })
      await wrapper.setProps({ lines: [...LINES, 'install: next'] })
      expect(body(wrapper).element.scrollTop).toBe(900)
    })

    it('stays where it is when lines arrive while follow is paused', async () => {
      const wrapper = mountPanel()
      await followButton(wrapper).trigger('click')
      expect(followButton(wrapper).text()).toBe('[FOLLOW]')
      scrollable(body(wrapper).element, { scrollHeight: 900, clientHeight: 200 })
      body(wrapper).element.scrollTop = 40
      await wrapper.setProps({ lines: [...LINES, 'install: next'] })
      expect(body(wrapper).element.scrollTop).toBe(40)
    })

    it('jumps to the end when FOLLOW is pressed again', async () => {
      const wrapper = mountPanel()
      await followButton(wrapper).trigger('click')
      scrollable(body(wrapper).element, { scrollHeight: 900, clientHeight: 200 })
      await followButton(wrapper).trigger('click')
      expect(body(wrapper).element.scrollTop).toBe(900)
      expect(followButton(wrapper).text()).toBe('[PAUSE FOLLOW]')
    })

    it('pauses itself when the analyst scrolls up to read, and follows again at the end', async () => {
      const wrapper = mountPanel()
      scrollable(body(wrapper).element, { scrollHeight: 900, clientHeight: 200 })
      body(wrapper).element.scrollTop = 100
      await body(wrapper).trigger('scroll')
      expect(followButton(wrapper).text()).toBe('[FOLLOW]')
      body(wrapper).element.scrollTop = 700
      await body(wrapper).trigger('scroll')
      expect(followButton(wrapper).text()).toBe('[PAUSE FOLLOW]')
    })
  })

  describe('the lines of the step protocol', () => {
    const PROTOCOL = [
      '== step install',
      'STEP Windows is provisioning itself: install 32-bit Python 3.11',
      'LOG guest: 2026-10-21 12:01:02  STEP install 32-bit Python 3.11',
      'PROGRESS 22',
      'LOG Windows is installing, about 3 min so far (estimated)',
      '== step provision',
      'PROGRESS 40',
    ]

    it('shows the text of a LOG line without the protocol word, and dims the guest’s own', () => {
      const wrapper = mountPanel(PROTOCOL)
      const line = (fragment: string) => wrapper.findAll('.build-log__line').find((row) => row.text().includes(fragment))!
      expect(line('STEP install 32-bit').text()).toBe('guest: 2026-10-21 12:01:02  STEP install 32-bit Python 3.11')
      expect(line('STEP install 32-bit').classes()).toContain('build-log__line--guest')
      expect(line('about 3 min').text()).toBe('Windows is installing, about 3 min so far (estimated)')
      expect(line('about 3 min').classes()).not.toContain('build-log__line--guest')
    })

    it('never prints a bare PROGRESS figure: each is a thin bar labelled with the step it belongs to', () => {
      const wrapper = mountPanel(PROTOCOL)
      expect(wrapper.text()).not.toContain('PROGRESS')
      const bars = wrapper.findAll('[data-build="log-progress"]')
      expect(bars.map((bar) => bar.text())).toEqual(['INSTALL 22%', 'PROVISION 40%'])
      expect(bars.map((bar) => bar.find('progress').attributes('value'))).toEqual(['22', '40'])
    })

    it('labels a PROGRESS figure that comes before any step line without a name', () => {
      const wrapper = mountPanel(['PROGRESS 5'])
      expect(wrapper.find('[data-build="log-progress"]').text()).toBe('5%')
    })

    it('still copies the raw lines', () => {
      const wrapper = mountPanel(PROTOCOL)
      expect(wrapper.findComponent({ name: 'CopyButton' }).props('text')).toBe(PROTOCOL.join('\n'))
    })
  })
})
