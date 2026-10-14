const pad = (value: number): string => String(value).padStart(2, '0')

/** Renders an ISO instant in UTC as `YYYY-MM-DD HH:mm:ss UTC`, the same for every viewer and every screen. */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const day = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
  const time = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`
  return `${day} ${time} UTC`
}

/** Renders an ISO instant's UTC time of day to the millisecond, `HH:mm:ss.SSS`, for ranges inside one analysis. */
export function formatClockTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const time = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`
  return `${time}.${String(date.getUTCMilliseconds()).padStart(3, '0')}`
}

/** Renders an ISO instant as `YYYY-MM-DD HH:mm:ss.SSS UTC`, for the one event a detail view is about. */
export function formatPreciseTimestamp(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const day = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
  return `${day} ${formatClockTime(iso)} UTC`
}
