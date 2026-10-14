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

/** Typing in the query bar asks for fields, values and validation on every pause: a failure there is not toast-worthy. */
export const QUIET_ON_QUERY_FAILURES = quietOn(404, 422, 500, 502, 504)
