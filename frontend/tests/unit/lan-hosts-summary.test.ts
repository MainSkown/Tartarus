import { describe, expect, it } from 'vitest'
import type { LanHost } from '@/api'
import { describeHosts } from '@/services/lan-hosts'

function host(role: string, n = 1): LanHost {
  return { fqdn: `${role}${n}.corp.local`, address: `192.168.150.${200 + n}`, role, services: [] }
}

describe('describeHosts', () => {
  it('counts the hosts and lists each role once, in the order the preset gives them', () => {
    const hosts = [host('domain-controller'), host('file-server'), host('workstation', 1), host('workstation', 2), host('printer')]

    expect(describeHosts(hosts)).toBe('5 hosts: domain-controller, file-server, workstation ×2, printer')
  })

  it('uses the singular for a single host', () => {
    expect(describeHosts([host('nas')])).toBe('1 host: nas')
  })

  it('says there is no host when the preset lists none', () => {
    expect(describeHosts([])).toBe('no hosts')
  })
})
