const pad = (value: number): string => String(value).padStart(2, '0')

/** Renders an ISO instant in the viewer's timezone as `YYYY-MM-DD HH:mm`. */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  return `${day} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
