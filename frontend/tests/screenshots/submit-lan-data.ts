import type { Page } from '@playwright/test'
import type { ErrorEnvelope, LanHost, LanPreset } from '../../src/api/types.gen'

function host(role: string, index: number, kinds: string[] = ['smb']): LanHost {
  return {
    fqdn: `${role.replace(/-/g, '')}${index}.corp.local`,
    address: `192.168.150.${200 + index}`,
    role,
    services: kinds.map((kind) => ({ kind, port: 445 })),
  }
}

export const SMALL_OFFICE: LanPreset = {
  id: 'small-office',
  name: 'Small office',
  description: 'A domain controller, a file server, two workstations, a SQL server and a printer on one corp.local network.',
  hosts: [
    host('domain-controller', 1, ['smb', 'ldap', 'rdp', 'winrm']),
    host('file-server', 2),
    host('workstation', 3, ['smb', 'rdp']),
    host('workstation', 4, ['smb', 'rdp']),
    host('sql-server', 5, ['smb', 'mssql']),
    host('printer', 6),
  ],
}

export const FLAT_HOME: LanPreset = {
  id: 'flat-home',
  name: 'Flat home LAN',
  description: 'A NAS, a desktop, a laptop and a printer on a home.lan network.',
  hosts: [host('nas', 1, ['smb', 'ssh']), host('workstation', 2), host('workstation', 3), host('printer', 4)],
}

export const DOMAIN_SERVERS: LanPreset = {
  id: 'domain-servers',
  name: 'Domain with servers',
  description: 'Two domain controllers and a tier of application, SQL, file, web and jump servers on lab.internal.',
  hosts: [
    host('domain-controller', 1),
    host('domain-controller', 2),
    host('application-server', 3),
    host('sql-server', 4),
    host('file-server', 5),
    host('web-server', 6),
    host('jump-host', 7, ['ssh', 'rdp']),
  ],
}

export const THREE_PRESETS: LanPreset[] = [SMALL_OFFICE, FLAT_HOME, DOMAIN_SERVERS]

export const LONG_PRESET: LanPreset = {
  id: 'campus-with-an-unreasonably-long-identifier-for-the-sake-of-wrapping',
  name: 'Regional headquarters campus network with several buildings, a datacentre and a disaster recovery site',
  description: `${'A very long description that keeps going well past what fits on a line in the dialog. '.repeat(3)}Hostnames_without_any_break_opportunity_${'x'.repeat(80)}.`,
  hosts: Array.from({ length: 9 }, (_, index) => host(index % 3 === 0 ? 'domain-controller' : 'application-server-in-the-datacentre', index + 1)),
}

export const PRESETS_DOWN: ErrorEnvelope = {
  error: { code: 'guest_control_unreachable', message: 'The guest control service is not reachable', details: {} },
}

interface LanPresetsReply {
  status?: number
  body: LanPreset[] | ErrorEnvelope
  gate?: Promise<void>
}

export async function mockLanPresets(page: Page, reply: LanPresetsReply): Promise<void> {
  await page.route(
    (url) => url.pathname === '/api/lan-presets',
    async (route) => {
      await reply.gate
      await route.fulfill({ status: reply.status ?? 200, json: reply.body })
    },
  )
}
