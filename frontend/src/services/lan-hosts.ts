import type { LanHost } from '@/api'
import { t } from '@/i18n'

function roleLabel(role: string, hosts: LanHost[]): string {
  const count = hosts.filter((host) => host.role === role).length
  return count === 1 ? role : t('submit.lan.preset.role', { role, count })
}

/** How many fake hosts a preset has and their roles, as the backend names them, each once. */
export function describeHosts(hosts: LanHost[]): string {
  const roles = [...new Set(hosts.map((host) => host.role))]
  return t('submit.lan.preset.hosts', { roles: roles.map((role) => roleLabel(role, hosts)).join(', ') }, hosts.length)
}
