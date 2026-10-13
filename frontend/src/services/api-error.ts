export const GENERIC_ERROR_MESSAGE = 'Something went wrong talking to the backend.'

/** The message of the backend's error envelope, or a generic one for anything else. */
export function errorMessage(error: unknown): string {
  const message = (error as { error?: { message?: unknown } } | undefined)?.error?.message
  return typeof message === 'string' ? message : GENERIC_ERROR_MESSAGE
}
