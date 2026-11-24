import type { FlowRow, HostRow, NetworkView } from '../../src/api/types.gen'
import { realView, type ViewMock } from './fixtures'

export const LONG_LAN_HOST = `${'workstation-with-a-very-long-hostname-'.repeat(3)}finance.corp.example.lan`
export const LONG_LAN_ROLE = 'domain-controller-and-certificate-authority-for-the-finance-forest'

const ordinaryHosts: HostRow[] = realView<NetworkView>('network').hosts.items.map((host) => ({
  ...host,
  simulated: false,
  lan_host: null,
  lan_role: null,
}))

export function fakeHost(overrides: Partial<HostRow> & Pick<HostRow, 'host' | 'lan_host' | 'lan_role'>): HostRow {
  return { kind: 'ip', count: 14, related: [], simulated: true, ...overrides }
}

export const FILE_SERVER = fakeHost({ host: '192.168.150.20', lan_host: 'fileserver.corp.lan', lan_role: 'file-server', related: ['share.corp.lan'] })
export const DOMAIN_CONTROLLER = fakeHost({ host: '192.168.150.21', lan_host: 'dc01.corp.lan', lan_role: 'domain-controller', count: 3 })
export const SHARE_HOST = fakeHost({ host: '192.168.150.22', lan_host: 'backup.corp.lan', lan_role: 'backup-server', count: 2 })

export function hostsView(items: HostRow[]): ViewMock {
  const view = realView<NetworkView>('network')
  return { body: { ...view, hosts: { items, total: items.length } } }
}

export const MIXED_HOSTS: HostRow[] = [FILE_SERVER, ...ordinaryHosts.slice(0, 1), DOMAIN_CONTROLLER, ...ordinaryHosts.slice(1), SHARE_HOST]

export const NO_FAKE_HOSTS: HostRow[] = ordinaryHosts

export const ONLY_FAKE_HOSTS: HostRow[] = [FILE_SERVER, DOMAIN_CONTROLLER, SHARE_HOST]

export const LONG_FAKE_HOSTS: HostRow[] = [
  fakeHost({ host: '192.168.150.30', lan_host: LONG_LAN_HOST, lan_role: LONG_LAN_ROLE, related: ['a.corp.lan', 'b.corp.lan'] }),
  ...ordinaryHosts.slice(0, 1),
]

export function flowsView(): ViewMock {
  const view = realView<NetworkView>('network')
  const [flow] = view.flows.items as FlowRow[]
  const plain: FlowRow = { ...flow!, simulated: false }
  const toFileServer: FlowRow = {
    ...flow!,
    event_id: 'flow-lan-1',
    destination_ip: '192.168.150.20',
    destination_port: 445,
    transport: 'tcp',
    simulated: true,
  }
  const toDomainController: FlowRow = {
    ...flow!,
    event_id: 'flow-lan-2',
    destination_ip: '192.168.150.21',
    destination_port: 88,
    transport: 'tcp',
    simulated: true,
  }
  const items = [toFileServer, plain, toDomainController]
  return { body: { ...view, flows: { items, total: items.length } } }
}
