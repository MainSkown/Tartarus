import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import GuestMediaList from '@/components/guest/GuestMediaList.vue'
import type { MediaChoice } from '@/composables/use-guest-wizard'
import { BROKEN_MEDIA, mediaEntry } from './guest-wizard-fixtures'

const WIN11: MediaChoice = { entry: mediaEntry(), profileName: 'Windows 11' }
const BROKEN: MediaChoice = { entry: BROKEN_MEDIA, unavailable: BROKEN_MEDIA.error! }
const UNREAD: MediaChoice = { entry: mediaEntry({ file: 'ubuntu.iso', profile: 'ubuntu' }), unavailable: 'No installed profile reads this image (ubuntu)' }

type Props = InstanceType<typeof GuestMediaList>['$props']

function mountList(props: Partial<Props> = {}) {
  return mount(GuestMediaList, { global: { plugins: [Quasar] }, props: { choices: [WIN11, BROKEN], ...props } })
}

const rows = (wrapper: ReturnType<typeof mountList>) => wrapper.findAll('[role="radio"]')

describe('GuestMediaList', () => {
  it('lists the file, its size, the profile and what the scan read', () => {
    const text = rows(mountList())[0]!.text()
    expect(text).toContain('Win11_25H2_Polish_x64_v2.iso')
    expect(text).toContain('7.3 GB')
    expect(text).toContain('Windows 11')
    expect(text).toContain('10.0.26200')
    expect(text).toContain('pl-PL')
    expect(text).toContain('x64')
    expect(text).toContain('2 editions')
  })

  it('emits the file of the row pressed', async () => {
    const wrapper = mountList()
    await rows(wrapper)[0]!.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[WIN11.entry.file]])
  })

  it('marks the selected row', () => {
    const wrapper = mountList({ selected: WIN11.entry.file })
    expect(rows(wrapper).map((row) => row.attributes('aria-checked'))).toEqual(['true', 'false'])
  })

  it('shows an image with an error disabled, with the message', async () => {
    const wrapper = mountList()
    const broken = rows(wrapper)[1]!
    expect(broken.attributes('aria-disabled')).toBe('true')
    expect(broken.text()).toContain('notes.iso')
    expect(broken.text()).toContain('no install.wim or install.esd found')
    await broken.trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('disables an image no installed profile reads, with the reason', () => {
    const row = rows(mountList({ choices: [UNREAD] }))[0]!
    expect(row.attributes('aria-disabled')).toBe('true')
    expect(row.text()).toContain('No installed profile reads this image (ubuntu)')
  })

  it('shows the server refusal of the chosen file under the list', () => {
    const wrapper = mountList({ error: 'is not in the installation media list' })
    expect(wrapper.get('[role="alert"]').text()).toBe('is not in the installation media list')
  })

  it('wraps a very long file name instead of widening the row', () => {
    const file = `${'Win11_25H2_'.repeat(12)}.iso`
    const name = rows(mountList({ choices: [{ entry: mediaEntry({ file }), profileName: 'Windows 11' }] }))[0]!.get('.media-row__file')
    expect(name.attributes('title')).toBe(file)
  })

  describe('with no media', () => {
    it('says where to put the image', () => {
      const wrapper = mountList({ choices: [] })
      expect(wrapper.text()).toContain('no installation media found')
      expect(wrapper.get('code').text()).toBe('data/iso')
      expect(rows(wrapper)).toHaveLength(0)
    })
  })

  it('emits reload from the RELOAD button, with or without media', async () => {
    for (const choices of [[], [WIN11]]) {
      const wrapper = mountList({ choices })
      await wrapper.get('button.media-list__reload').trigger('click')
      expect(wrapper.emitted('reload')).toHaveLength(1)
    }
  })
})
