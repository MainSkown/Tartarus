import { t } from '@/i18n'

export function genericErrorMessage(): string {
  return t('shell.apiError.generic')
}

/** The message of the backend's error envelope, or a generic one for anything else. */
export function errorMessage(error: unknown): string {
  const message = (error as { error?: { message?: unknown } } | undefined)?.error?.message
  return typeof message === 'string' ? message : genericErrorMessage()
}
