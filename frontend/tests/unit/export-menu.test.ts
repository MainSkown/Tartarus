import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { analysisFixture } from './analysis-fixtures'

vi.mock('@/composables/use-ioc-export', () => ({ useIocExport: () => ({ download: vi.fn(), downloading: { value: undefined } }) }))
vi.mock('@/services/report-dialog', () => ({ openReportDialog: vi.fn() }))

const ExportMenu = (await import('@/components/ExportMenu.vue')).default

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ExportMenu', () => {
  it('is an EXPORT button that opens a menu with the export entries of the analysis', async () => {
    const analysis = analysisFixture({ id: 193 })
    const wrapper = mount(ExportMenu, { attachTo: document.body, global: { plugins: [Quasar] }, props: { analysis } })

    const button = wrapper.get('button.export-menu__button')
    expect(button.text()).toBe('[EXPORT]')
    expect(document.querySelector('.export-entries')).toBeNull()

    await button.trigger('click')
    await flushPromises()

    expect(document.querySelector('.export-entries')).not.toBeNull()
    expect(document.body.textContent).toContain('STIX 2.1')
    expect(document.body.textContent).toContain('PDF')
  })
})
