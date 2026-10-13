export const NOT_FOUND_STATUS = 404

/** Request `meta` that tells the API error interceptor these statuses are handled by the caller, so no toast. */
export type QuietStatuses = { quietStatuses: number[] }

export function quietOn(...statuses: number[]): QuietStatuses {
  return { quietStatuses: statuses }
}

export function isQuietFailure(response: Response | undefined, meta: Record<string, unknown> | undefined): boolean {
  const quiet = meta?.quietStatuses
  return response !== undefined && Array.isArray(quiet) && quiet.includes(response.status)
}
