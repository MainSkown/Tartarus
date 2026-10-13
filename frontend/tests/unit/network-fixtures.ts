import type { NetworkView } from '@/api'

const CMD = { pid: 2476, name: 'cmd.exe' }

export function networkView(overrides: Partial<NetworkView> = {}): NetworkView {
  return {
    dns: {
      items: [
        {
          event_id: 'dns-1',
          time: '2026-10-13T15:39:33.863000Z',
          query: 'www.msftconnecttest.com',
          type: 'A',
          answers: ['192.168.150.1', '192.168.150.2'],
          process: null,
        },
        {
          event_id: 'dns-2',
          time: '2026-10-13T15:39:34.100000Z',
          query: 'evil.example.org',
          type: null,
          answers: [],
          process: CMD,
        },
      ],
      total: 2,
    },
    http: {
      items: [
        {
          event_id: 'http-1',
          time: '2026-10-13T15:39:33.872000Z',
          method: 'GET',
          url: 'http://ipv6.msftconnecttest.com/connecttest.txt',
          host: 'ipv6.msftconnecttest.com',
          status: 200,
          user_agent: 'Microsoft NCSI',
          process: CMD,
        },
        {
          event_id: 'http-2',
          time: '2026-10-13T15:39:35.000000Z',
          method: null,
          url: 'http://192.168.150.1/',
          host: null,
          status: null,
          user_agent: null,
          process: null,
        },
      ],
      total: 2,
    },
    tls: { items: [], total: 0 },
    flows: {
      items: [
        {
          event_id: 'flow-1',
          time: '2026-10-13T15:39:23.001000Z',
          transport: 'tcp',
          source_ip: '192.168.150.10',
          source_port: 64155,
          destination_ip: '192.168.150.1',
          destination_port: 443,
          process: null,
        },
        {
          event_id: 'flow-2',
          time: '2026-10-13T15:39:24.001000Z',
          transport: 'udp',
          source_ip: '192.168.150.10',
          source_port: null,
          destination_ip: null,
          destination_port: null,
          process: CMD,
        },
      ],
      total: 214,
    },
    alerts: { items: [], total: 0 },
    hosts: {
      items: [
        { host: '192.168.150.1', kind: 'ip', count: 210, related: ['www.msftconnecttest.com', 'evil.example.org'] },
        { host: 'evil.example.org', kind: 'domain', count: 3, related: [] },
      ],
      total: 2,
    },
    simulated: true,
    ...overrides,
  }
}
