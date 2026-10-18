import { n } from '@/i18n'

export function formatCount(value: number): string {
  return n(value, 'count')
}
