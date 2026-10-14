import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import type { Artifact } from '@/api'
import ArtifactTable from '@/components/ArtifactTable.vue'
import CopyButton from '@/components/CopyButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import { artifactFixture, DROPPER_HASH } from './artifacts-fixtures'
import { filterEventsPlugins } from './filter-events-plugins'

const { plugins, router, query } = await filterEventsPlugins()

function mountTable(artifacts: Artifact[], props: { showFamily?: boolean } = {}) {
  return mount(ArtifactTable, { global: { plugins }, props: { analysisId: 45, artifacts, ...props } })
}

function headers(wrapper: ReturnType<typeof mountTable>): string[] {
  return wrapper.findAll('th').map((th) => th.text())
}

describe('ArtifactTable', () => {
  it('lists the file with its path, size, type, process and a hash that can be copied', () => {
    const wrapper = mountTable([artifactFixture()])
    const cells = wrapper.findAll('tbody tr')[0]!
    expect(headers(wrapper)).toEqual(['NAME', 'GUEST PATH', 'SIZE', 'TYPE', 'SHA256', 'YARA', 'PROCESS', 'DOWNLOAD'])
    expect(cells.text()).toContain('tartarus-benign.txt')
    expect(cells.text()).toContain('C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt')
    expect(cells.text()).toContain('33 B')
    expect(cells.text()).toContain('ASCII text, with CRLF line terminators')
    expect(cells.findComponent(ProcessChip).props('process')).toEqual({ pid: 9708, name: 'benign.exe' })
    expect(cells.findComponent(CopyButton).props()).toEqual({ text: DROPPER_HASH, what: 'SHA-256' })
  })

  it('cuts the hash short but keeps the whole of it in the tooltip', () => {
    const cell = mountTable([artifactFixture()]).find('.cell-sha')
    expect(cell.text()).toContain(DROPPER_HASH.slice(0, 12))
    expect(cell.text()).not.toContain(DROPPER_HASH)
    expect(cell.find('[title]').attributes('title')).toBe(DROPPER_HASH)
  })

  it('keeps a long path and name reachable through their titles', () => {
    const guest_path = `C:\\${'deeply\\nested\\'.repeat(20)}payload.bin`
    const wrapper = mountTable([artifactFixture({ guest_path, name: 'n'.repeat(200) })])
    expect(wrapper.find('.cell-path').attributes('title')).toBe(guest_path)
    expect(wrapper.find('.cell-name').attributes('title')).toBe('n'.repeat(200))
  })

  it('shows a dash for what the artifact does not have', () => {
    const wrapper = mountTable([
      artifactFixture({ size: null, sha256: null, type: null, guest_path: null, source_process: null }),
    ])
    expect(wrapper.find('.cell-sha').text()).toBe('–')
    expect(wrapper.find('.cell-path').text()).toBe('–')
    expect(wrapper.find('.cell-size').text()).toBe('–')
    expect(wrapper.findComponent(CopyButton).exists()).toBe(false)
  })

  it('names each YARA hit', () => {
    const wrapper = mountTable([artifactFixture({ yara: ['Emotet', 'UPX'] })])
    expect(wrapper.findAll('.yara-hit').map((hit) => hit.text())).toEqual(['Emotet', 'UPX'])
  })

  it('adds the family column from the CAPE type when asked', () => {
    const wrapper = mountTable([artifactFixture({ cape_type: 'AgentTesla Payload' })], { showFamily: true })
    expect(headers(wrapper)).toContain('FAMILY')
    expect(wrapper.find('.cell-family').text()).toBe('AgentTesla Payload')
  })

  it('has no family column by default', () => {
    expect(headers(mountTable([artifactFixture()]))).not.toContain('FAMILY')
  })

  describe('downloads', () => {
    it('links to the API download of the artifact', () => {
      const link = mountTable([artifactFixture({ id: 'abc123' })]).find('a.download-link')
      expect(link.attributes('href')).toBe('/api/analyses/45/artifacts/abc123/download')
      expect(link.text()).toBe('[DOWNLOAD]')
    })

    it('says in a caption that the download is a zip with the password infected', () => {
      expect(mountTable([artifactFixture()]).find('.download-note').text()).toContain('infected')
    })

    it('shows a disabled not-kept state instead of a link for a file that is gone', () => {
      const wrapper = mountTable([artifactFixture({ downloadable: false })])
      expect(wrapper.find('a.download-link').exists()).toBe(false)
      const notKept = wrapper.find('.download-unavailable')
      expect(notKept.text()).toBe('not kept')
      expect(notKept.attributes('aria-disabled')).toBe('true')
    })

    it('leaves out the caption when nothing can be downloaded', () => {
      expect(mountTable([artifactFixture({ downloadable: false })]).find('.download-note').exists()).toBe(false)
    })
  })
})

describe('ArtifactTable show events actions', () => {
  beforeEach(() => query.reset())

  const labels = (cell: { findAll: (selector: string) => { attributes: (name: string) => string | undefined }[] }) =>
    cell.findAll('button').map((button) => button.attributes('aria-label'))

  it('filters on the guest path from the path cell', () => {
    const row = mountTable([artifactFixture()]).find('tbody tr')
    expect(labels(row.findAll('td')[1]! as never)).toEqual([
      'Show events with file.path: C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt',
    ])
  })

  it('filters on the SHA-256 from the hash cell, next to the copy button', () => {
    const cell = mountTable([artifactFixture()]).find('.cell-sha')
    expect(labels(cell as never)).toEqual([`Copy SHA-256`, `Show events with file.hash.sha256: ${DROPPER_HASH}`])
  })

  it('offers nothing for a file without a path or a hash', () => {
    const wrapper = mountTable([artifactFixture({ guest_path: null, sha256: null })])
    expect(wrapper.findAll('tbody tr')[0]!.findAll('button')).toHaveLength(0)
  })

  it('applies the chip and opens Events from the path button', async () => {
    const wrapper = mountTable([artifactFixture({ guest_path: 'C:\\a.exe' })])
    await wrapper.find('tbody td [aria-label^="Show events with file.path"]').trigger('click')
    await flushPromises()
    expect(query.chips).toEqual([{ field: 'file.path', value: 'C:\\a.exe', negate: false }])
    expect(router.currentRoute.value.params.tab).toBe('events')
  })
})
