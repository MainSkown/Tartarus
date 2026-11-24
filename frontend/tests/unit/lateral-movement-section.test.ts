import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import HashRow from '@/components/HashRow.vue'
import LateralMovementSection from '@/components/LateralMovementSection.vue'
import { HOSTILE, lanCredential, lanFile, lanHost, lanService, lanSummary, SHA256 } from './lan-summary-fixtures'
import type { LanSummary } from '@/api'

function mountSection(lan: LanSummary | null | undefined) {
  return mount(LateralMovementSection, { global: { plugins: [Quasar] }, props: { lan } })
}

describe('LateralMovementSection visibility', () => {
  it.each([null, undefined])('renders nothing at all when the feature was off (%s)', (lan) => {
    expect(mountSection(lan).html()).toBe('<!--v-if-->')
  })

  it('says the sample did nothing when no host was touched, and names the preset', () => {
    const wrapper = mountSection(lanSummary({ hosts: [] }))
    expect(wrapper.text()).toContain('the sample did nothing on the fake local network')
    expect(wrapper.text()).toContain('Small office')
    expect(wrapper.find('.lan-host').exists()).toBe(false)
  })
})

describe('LateralMovementSection hosts', () => {
  it('titles a host with its name and shows its address, role and first and last contact', () => {
    const host = mountSection(lanSummary()).get('.lan-host')
    expect(host.get('h3').text()).toBe('fs01.corp.local')
    expect(host.text()).toContain('192.168.150.201')
    expect(host.text()).toContain('file-server')
    expect(host.text()).toContain('2026-11-23 12:00:20 UTC')
    expect(host.text()).toContain('2026-11-23 12:00:40 UTC')
  })

  it('names the preset once for any number of hosts', () => {
    const wrapper = mountSection(lanSummary({ hosts: [lanHost(), lanHost({ fqdn: 'dc01.corp.local' })] }))
    expect(wrapper.findAll('.lan-host')).toHaveLength(2)
    expect(wrapper.text().match(/Small office/g)).toHaveLength(1)
  })

  it('lists each service with its port, attempts and times', () => {
    const lan = lanSummary({
      hosts: [
        lanHost({
          services: [
            lanService(),
            lanService({ service: 'rdp', port: 3389, attempts: 1, first: '2026-11-23T12:01:00.250Z', last: '2026-11-23T12:01:00.250Z' }),
          ],
        }),
      ],
    })
    const rows = mountSection(lan).findAll('.lan-services tbody tr')
    expect(rows.map((row) => row.findAll('td').map((cell) => cell.text()))).toEqual([
      ['smb', '445', '5 attempts', '12:00:20.000', '12:00:40.000'],
      ['rdp', '3389', '1 attempt', '12:01:00.250', '12:01:00.250'],
    ])
  })

  it('shows a port the host does not serve and a flood aggregate with no port as such', () => {
    const lan = lanSummary({
      hosts: [lanHost({ services: [lanService({ service: null, port: 8080 }), lanService({ service: 'ssh', port: null })] })],
    })
    const cells = mountSection(lan)
      .findAll('.lan-services tbody tr')
      .map((row) => row.findAll('td').map((cell) => cell.text()))
    expect(cells[0]!.slice(0, 2)).toEqual(['no service', '8080'])
    expect(cells[1]!.slice(0, 2)).toEqual(['ssh', '–'])
  })
})

describe('LateralMovementSection credentials', () => {
  const lan = lanSummary({
    hosts: [
      lanHost({
        credentials: [
          lanCredential(),
          lanCredential({ user: 'guest', domain: '', mechanism: 'basic', count: 1, success: false, secret_as_sent: null }),
        ],
      }),
    ],
  })

  it('shows user, domain, mechanism, attempts and whether the host accepted it', () => {
    const rows = mountSection(lan).findAll('.lan-credential')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('Administrator')
    expect(rows[0]!.text()).toContain('CORP')
    expect(rows[0]!.text()).toContain('ntlm')
    expect(rows[0]!.text()).toContain('3 attempts')
    expect(rows[0]!.get('.lan-credential__result').text()).toBe('accepted')
    expect(rows[1]!.get('.lan-credential__result').text()).toBe('refused')
    expect(rows[1]!.text()).toContain('1 attempt')
  })

  it('labels the secret as the sample\'s and omits the line when none was sent', () => {
    const rows = mountSection(lan).findAll('.lan-credential')
    expect(rows[0]!.text()).toContain('SECRET AS SENT BY THE SAMPLE')
    expect(rows[0]!.get('.lan-credential__secret').text()).toBe('Winter2026!')
    expect(rows[1]!.find('.lan-credential__secret').exists()).toBe(false)
  })

  it('offers the whole secret to copy and the whole value on hover', () => {
    const secret = 'S'.repeat(300)
    const wrapper = mountSection(lanSummary({ hosts: [lanHost({ credentials: [lanCredential({ secret_as_sent: secret })] })] }))
    expect(wrapper.get('.lan-credential__secret').attributes('title')).toBe(secret)
    expect(wrapper.get('.lan-credential .copy-button').attributes('aria-label')).toContain('secret')
  })

  it('shows a secret with no user as an unattributed secret', () => {
    const wrapper = mountSection(
      lanSummary({ hosts: [lanHost({ credentials: [lanCredential({ user: '', domain: '', mechanism: 'ntlm', count: 0, success: false, secret_as_sent: 'aad3b435' })] })] }),
    )
    const row = wrapper.get('.lan-credential')
    expect(row.text()).toContain('unattributed secret')
    expect(row.get('.lan-credential__secret').text()).toBe('aad3b435')
    expect(row.text()).toContain('0 attempts')
  })

  it('says how many credentials were left out', () => {
    const wrapper = mountSection(lanSummary({ hosts: [lanHost({ credentials: [lanCredential()], credentials_more: 1 })] }))
    expect(wrapper.get('.lan-host__more').text()).toBe('1 more credential not listed')
    const many = mountSection(lanSummary({ hosts: [lanHost({ credentials: [lanCredential()], credentials_more: 1234 })] }))
    expect(many.get('.lan-host__more').text()).toBe('1,234 more credentials not listed')
  })

  it('shows no credentials block for a host with none', () => {
    expect(mountSection(lanSummary()).find('.lan-credential').exists()).toBe(false)
  })
})

describe('LateralMovementSection files', () => {
  it('shows path, share, size and the hash through the shared hash row', () => {
    const wrapper = mountSection(lanSummary({ hosts: [lanHost({ files: [lanFile()] })] }))
    const file = wrapper.get('.lan-file')
    expect(file.get('.lan-file__path').text()).toBe('\\evil.exe')
    expect(file.text()).toContain('ADMIN$')
    expect(file.text()).toContain('60 KB')
    expect(file.getComponent(HashRow).props('hash')).toBe(SHA256)
  })

  it('shows a file with no size or hash without inventing either', () => {
    const wrapper = mountSection(lanSummary({ hosts: [lanHost({ files: [lanFile({ size: null, sha256: null })] })] }))
    const file = wrapper.get('.lan-file')
    expect(file.getComponent(HashRow).props('hash')).toBeNull()
    expect(file.find('.lan-file__size').text()).toBe('–')
  })

  it('says how many files were left out', () => {
    const wrapper = mountSection(lanSummary({ hosts: [lanHost({ files: [lanFile()], files_more: 40 })] }))
    expect(wrapper.get('.lan-host__more').text()).toBe('40 more files not listed')
    const one = mountSection(lanSummary({ hosts: [lanHost({ files: [lanFile()], files_more: 1 })] }))
    expect(one.get('.lan-host__more').text()).toBe('1 more file not listed')
  })

  it('adds no more-line when nothing was left out', () => {
    expect(mountSection(lanSummary({ hosts: [lanHost({ files: [lanFile()], files_more: 0 })] })).find('.lan-host__more').exists()).toBe(false)
  })
})

describe('LateralMovementSection truncated log', () => {
  it('warns that the counts are lower bounds when the log was cut', () => {
    const notice = mountSection(lanSummary({ truncated: true })).get('[role="alert"]')
    expect(notice.text()).toContain('lower bounds')
  })

  it('says nothing about it otherwise', () => {
    expect(mountSection(lanSummary()).find('[role="alert"]').exists()).toBe(false)
  })

  it('still warns when the cut log left no host to show', () => {
    expect(mountSection(lanSummary({ hosts: [], truncated: true })).find('[role="alert"]').exists()).toBe(true)
  })
})

describe('LateralMovementSection hostile text', () => {
  it('shows markup the sample sent as text and injects no element', () => {
    const lan = lanSummary({
      hosts: [
        lanHost({
          credentials: [lanCredential({ user: HOSTILE, domain: HOSTILE, secret_as_sent: HOSTILE })],
          files: [lanFile({ path: HOSTILE, share: HOSTILE })],
        }),
      ],
    })
    const wrapper = mountSection(lan)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.get('.lan-credential__secret').text()).toBe(HOSTILE)
    expect(wrapper.get('.lan-file__path').text()).toBe(HOSTILE)
    expect(wrapper.get('.lan-credential').text()).toContain(HOSTILE)
  })
})
