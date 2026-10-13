import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { NetworkView } from '@/api'
import { analysisFixture } from './analysis-fixtures'
import { networkView } from './network-fixtures'

const viewsNetworkMock = vi.fn()
vi.mock('@/api', () => ({
  viewsNetwork: (...args: unknown[]) => viewsNetworkMock(...args),
}))

const { default: NetworkTab } = await import('@/components/tabs/NetworkTab.vue')

async function mountTab(view: NetworkView = networkView()) {
  viewsNetworkMock.mockResolvedValue({ data: view })
  const wrapper = mount(NetworkTab, {
    props: { analysis: analysisFixture({ id: 45 }) },
    global: { plugins: [Quasar] },
  })
  await flushPromises()
  return wrapper
}

async function openSubTab(wrapper: Awaited<ReturnType<typeof mountTab>>, name: string) {
  const tab = wrapper.findAll('[role="tab"]').find((button) => button.text().startsWith(name))!
  await tab.trigger('click')
}

function headers(wrapper: Awaited<ReturnType<typeof mountTab>>): string[] {
  return wrapper.findAll('th').map((th) => th.text())
}

function bodyRows(wrapper: Awaited<ReturnType<typeof mountTab>>): string[][] {
  return wrapper.findAll('tbody tr').map((row) => row.findAll('td').map((cell) => cell.text()))
}

beforeEach(() => {
  viewsNetworkMock.mockReset()
})

describe('NetworkTab loading', () => {
  it('requests the network view of the analysis', async () => {
    await mountTab()
    expect(viewsNetworkMock).toHaveBeenCalledWith({ path: { analysis_id: 45 } })
  })

  it('shows the loader until the view arrives, and keeps its root marker', () => {
    viewsNetworkMock.mockReturnValue(new Promise(() => {}))
    const wrapper = mount(NetworkTab, {
      props: { analysis: analysisFixture({ id: 45 }) },
      global: { plugins: [Quasar] },
    })
    expect(wrapper.attributes('data-tab')).toBe('network')
    expect(wrapper.find('.loader').exists()).toBe(true)
  })

  it('shows the error and reloads on retry', async () => {
    viewsNetworkMock.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'index is down' } } })
    const wrapper = mount(NetworkTab, {
      props: { analysis: analysisFixture({ id: 45 }) },
      global: { plugins: [Quasar] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('failed to load: index is down')

    viewsNetworkMock.mockResolvedValue({ data: networkView() })
    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()

    expect(viewsNetworkMock).toHaveBeenCalledTimes(2)
    expect(wrapper.find('table').exists()).toBe(true)
  })
})

describe('NetworkTab sub-tabs', () => {
  it('lists the six sub-tabs with the count of each list', async () => {
    const wrapper = await mountTab()
    expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).toEqual([
      'DNS (2)',
      'HTTP (2)',
      'TLS (0)',
      'FLOWS (214)',
      'ALERTS (0)',
      'HOSTS (2)',
    ])
  })

  it('starts on DNS and marks the selected sub-tab', async () => {
    const wrapper = await mountTab()
    const selected = wrapper.findAll('[role="tab"][aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['DNS (2)'])
  })

  it('keeps the selection while the view is reloaded for another analysis', async () => {
    const wrapper = await mountTab()
    await openSubTab(wrapper, 'HOSTS')
    viewsNetworkMock.mockResolvedValue({ data: networkView() })

    await wrapper.setProps({ analysis: analysisFixture({ id: 46 }) })
    await flushPromises()

    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toBe('HOSTS (2)')
  })
})

describe('NetworkTab tables', () => {
  it('shows DNS queries with their answers and process', async () => {
    const wrapper = await mountTab()
    expect(headers(wrapper)).toEqual(['TIME', 'QUERY', 'TYPE', 'ANSWERS', 'PROCESS'])
    expect(bodyRows(wrapper)).toEqual([
      ['2026-10-13 15:39:33 UTC', 'www.msftconnecttest.com', 'A', '192.168.150.1, 192.168.150.2', '–'],
      ['2026-10-13 15:39:34 UTC', 'evil.example.org', '–', '–', 'cmd.exe (2476)'],
    ])
  })

  it('shows HTTP requests', async () => {
    const wrapper = await mountTab()
    await openSubTab(wrapper, 'HTTP')
    expect(headers(wrapper)).toEqual(['TIME', 'METHOD', 'URL', 'STATUS', 'USER AGENT', 'HOST', 'PROCESS'])
    expect(bodyRows(wrapper)[0]).toEqual([
      '2026-10-13 15:39:33 UTC',
      'GET',
      'http://ipv6.msftconnecttest.com/connecttest.txt',
      '200',
      'Microsoft NCSI',
      'ipv6.msftconnecttest.com',
      'cmd.exe (2476)',
    ])
    expect(bodyRows(wrapper)[1]!.slice(1)).toEqual(['–', 'http://192.168.150.1/', '–', '–', '–', '–'])
  })

  it('shows flows as transport, source and destination', async () => {
    const wrapper = await mountTab()
    await openSubTab(wrapper, 'FLOWS')
    expect(headers(wrapper)).toEqual(['TIME', 'TRANSPORT', 'SOURCE', 'DESTINATION', 'PROCESS'])
    expect(bodyRows(wrapper)[0]).toEqual([
      '2026-10-13 15:39:23 UTC',
      'tcp',
      '192.168.150.10:64155',
      '192.168.150.1:443',
      '–',
    ])
    expect(bodyRows(wrapper)[1]!.slice(1, 4)).toEqual(['udp', '192.168.150.10', '–'])
  })

  it('shows hosts with kind, count and related names', async () => {
    const wrapper = await mountTab()
    await openSubTab(wrapper, 'HOSTS')
    expect(headers(wrapper)).toEqual(['HOST', 'KIND', 'COUNT', 'RELATED'])
    expect(bodyRows(wrapper)).toEqual([
      ['192.168.150.1', 'ip', '210', 'www.msftconnecttest.com, evil.example.org'],
      ['evil.example.org', 'domain', '3', '–'],
    ])
  })

  it('shows TLS handshakes and alerts when a source provides them', async () => {
    const wrapper = await mountTab(
      networkView({
        tls: {
          items: [
            { event_id: 't1', time: '2026-10-13T15:40:00Z', server_name: 'a.example', ja3: 'abc', ja3s: 'def', process: null },
          ],
          total: 1,
        },
        alerts: {
          items: [
            { event_id: 'a1', time: '2026-10-13T15:41:00Z', signature: 'ET MALWARE beacon', severity: 'high', process: null },
          ],
          total: 1,
        },
      }),
    )
    await openSubTab(wrapper, 'TLS')
    expect(headers(wrapper)).toEqual(['TIME', 'SNI', 'JA3', 'JA3S', 'PROCESS'])
    expect(bodyRows(wrapper)[0]!.slice(1, 4)).toEqual(['a.example', 'abc', 'def'])
    await openSubTab(wrapper, 'ALERTS')
    expect(headers(wrapper)).toEqual(['TIME', 'SIGNATURE', 'SEVERITY', 'PROCESS'])
    expect(bodyRows(wrapper)[0]!.slice(1, 3)).toEqual(['ET MALWARE beacon', 'high'])
  })

  it.each(['TLS', 'ALERTS'])('says where the empty %s list will come from', async (name) => {
    const wrapper = await mountTab()
    await openSubTab(wrapper, name)
    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.text()).toContain('TLS and Suricata alerts arrive with a later milestone')
  })

  it('has no later-milestone note on an empty list that has a source', async () => {
    const wrapper = await mountTab(networkView({ dns: { items: [], total: 0 } }))
    expect(wrapper.text()).toContain('no DNS queries recorded')
    expect(wrapper.text()).not.toContain('later milestone')
  })

  it('says how many of the total are listed', async () => {
    const wrapper = await mountTab()
    await openSubTab(wrapper, 'FLOWS')
    expect(wrapper.find('.network-table__count').text()).toBe('listed 2 of 214')
  })

  it('titles a long URL with its full text', async () => {
    const url = `http://example.org/${'a'.repeat(300)}`
    const base = networkView()
    const wrapper = await mountTab(
      networkView({ http: { items: [{ ...base.http.items[0]!, url }], total: 1 } }),
    )
    await openSubTab(wrapper, 'HTTP')
    expect(wrapper.find(`[title="${url}"]`).exists()).toBe(true)
  })
})

describe('NetworkTab inetsim marking', () => {
  it('marks the tables when INetSim answered', async () => {
    const wrapper = await mountTab(networkView({ simulated: true }))
    expect(wrapper.find('.network-table__inetsim').exists()).toBe(true)
  })

  it('does not mark them when the traffic was real', async () => {
    const wrapper = await mountTab(networkView({ simulated: false }))
    expect(wrapper.find('.network-table__inetsim').exists()).toBe(false)
  })
})

describe('NetworkTab pcap', () => {
  it('links to the pcap of the analysis as a download', async () => {
    const wrapper = await mountTab()
    const link = wrapper.find('a[download]')
    expect(link.attributes('href')).toBe('/api/analyses/45/pcap')
    expect(link.text()).toContain('PCAP')
  })
})
