import type { AnalysisRead, LanCredential, LanHostSummary, LanServiceUse, LanSummary, LanWrittenFile } from '../../src/api/types.gen'
import { makeDetectedAnalysis } from './fixtures'

export const ID = 61

const SHA256 = '3f5a9c1e7b2d4860a1c3e5f79b0d2486ace13579bdf02468ace13579bdf02468'.slice(0, 64)
const HOSTILE = '<img src=x onerror=alert(1)>'
const AT = (clock: string): string => `2026-11-23T${clock}Z`

function service(name: string | null, port: number | null, attempts: number, first: string, last: string): LanServiceUse {
  return { service: name, port, attempts, first: AT(first), last: AT(last) }
}

function credential(user: string, domain: string, mechanism: string, count: number, success: boolean, secret: string | null): LanCredential {
  return { user, domain, mechanism, count, success, secret_as_sent: secret }
}

function file(path: string, share: string, size: number | null, sha256: string | null = SHA256): LanWrittenFile {
  return { path, share, size, sha256 }
}

function host(fields: Pick<LanHostSummary, 'fqdn' | 'address' | 'role' | 'services'> & Partial<LanHostSummary>): LanHostSummary {
  return {
    credentials: [],
    files: [],
    first: fields.services[0]!.first,
    last: fields.services[fields.services.length - 1]!.last,
    ...fields,
  }
}

function lan(hosts: LanHostSummary[], truncated = false): LanSummary {
  return {
    preset: { id: 'small-office', name: 'Small office' },
    hosts,
    totals: {
      hosts: hosts.length,
      attempts: hosts.reduce((sum, h) => sum + h.services.reduce((n, s) => n + s.attempts, 0), 0),
      credentials: hosts.reduce((sum, h) => sum + h.credentials.length + (h.credentials_more ?? 0), 0),
      files: hosts.reduce((sum, h) => sum + h.files.length + (h.files_more ?? 0), 0),
    },
    truncated,
  }
}

const FILE_SERVER = host({
  fqdn: 'fs01.corp.local',
  address: '192.168.150.201',
  role: 'file-server',
  services: [service('smb', 445, 14, '12:00:20', '12:03:40'), service('rdp', 3389, 1, '12:01:00.250', '12:01:00.250')],
  credentials: [
    credential('Administrator', 'CORP', 'ntlm', 3, true, 'Winter2026!'),
    credential('backup', 'CORP', 'ntlm', 2, false, 'aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0'),
  ],
  files: [file('\\evil.exe', 'ADMIN$', 61440), file('\\Windows\\Temp\\svc.dll', 'C$', 1_258_291)],
})

const DOMAIN_CONTROLLER = host({
  fqdn: 'dc01.corp.local',
  address: '192.168.150.200',
  role: 'domain-controller',
  services: [
    service('ldap', 389, 120, '12:00:05', '12:02:11'),
    service('smb', 445, 3, '12:00:07', '12:00:09'),
    service('winrm', 5985, 7, '12:02:30', '12:02:59'),
    service('kerberos', 88, 48, '12:00:06', '12:02:10'),
    service(null, 8080, 1, '12:00:30', '12:00:30'),
    service('ssh', null, 250, '12:01:00', '12:01:20'),
  ],
  credentials: [
    credential('krbtgt', 'CORP', 'kerberos', 12, false, null),
    credential('svc_sql', 'CORP', 'ntlm', 4, true, 'Passw0rd!'),
    credential('', '', 'ntlm', 0, false, '5f4dcc3b5aa765d61d8327deb882cf99'),
  ],
})

const SQL_SERVER = host({
  fqdn: 'sql01.corp.local',
  address: '192.168.150.210',
  role: 'sql-server',
  services: [service('mssql', 1433, 31, '12:02:00', '12:02:45')],
  credentials: [credential('sa', '', 'sql', 31, true, 'sa')],
  files: [file('D:\\data\\payload.bin', 'D$', null, null)],
})

const LONG_PATH = `\\Users\\${'a_very_long_directory_name_'.repeat(8)}\\Documents\\${'nested_folder_'.repeat(10)}payload_final_v2_REAL.exe`
const LONG_USER = `${'administrator-with-an-extraordinarily-long-account-name-'.repeat(4)}@corp.local`
const LONG_SECRET = `${'Tr0ub4dor&3-'.repeat(40)}end-of-secret`

export const ANALYSIS_STATES = {
  hidden: undefined,
  empty: lan([]),
  oneService: lan([host({ fqdn: 'fs01.corp.local', address: '192.168.150.201', role: 'file-server', services: [service('smb', 445, 5, '12:00:20', '12:00:40')] })]),
  threeHosts: lan([DOMAIN_CONTROLLER, FILE_SERVER, SQL_SERVER]),
  truncated: lan([FILE_SERVER, SQL_SERVER], true),
  long: lan([
    host({
      fqdn: 'fs01.corp.local',
      address: '192.168.150.201',
      role: 'file-server',
      services: [service('smb', 445, 2, '12:00:20', '12:00:40')],
      credentials: [credential(LONG_USER, 'CORP-WITH-A-VERY-LONG-DOMAIN-NAME-THAT-KEEPS-GOING-AND-GOING', 'ntlmssp-negotiated-with-extension', 1, true, LONG_SECRET)],
      files: [file(LONG_PATH, `${'SHARE_'.repeat(20)}$`, 4_294_967_296)],
    }),
  ]),
  hostile: lan([
    host({
      fqdn: 'fs01.corp.local',
      address: '192.168.150.201',
      role: 'file-server',
      services: [service('smb', 445, 2, '12:00:20', '12:00:40')],
      credentials: [credential(HOSTILE, HOSTILE, 'ntlm', 1, true, HOSTILE), credential('<script>alert(2)</script>', '', 'basic', 1, false, '"><svg onload=alert(3)>')],
      files: [file(HOSTILE, HOSTILE, 10)],
    }),
  ]),
  more: lan([
    {
      ...FILE_SERVER,
      credentials_more: 1,
      files_more: 1243,
    },
    { ...SQL_SERVER, credentials_more: 12_400 },
  ]),
} satisfies Record<string, LanSummary | undefined>

/** A finished, detected analysis whose summary carries the given fake-network section (none, as when the feature was off). */
export function analysisWithLan(summaryLan?: LanSummary): AnalysisRead {
  const base = makeDetectedAnalysis({ id: ID, guest: 'lab5', guest_badges: ['DEFENDER ON', 'SYSMON'] })
  return { ...base, summary: { ...base.summary, ...(summaryLan === undefined ? {} : { lan: summaryLan }) } }
}
