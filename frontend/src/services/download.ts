const REVOKE_DELAY_MS = 10_000

const EXTENDED_NAME = /filename\*\s*=\s*[^']*'[^']*'([^;]+)/i
const PLAIN_NAME = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/i

function decodeExtended(value: string): string | undefined {
  try {
    return decodeURIComponent(value.trim())
  } catch {
    return undefined
  }
}

/** The file name a `Content-Disposition` header proposes, stripped of any directory part. */
export function filenameFromDisposition(header: string | null | undefined): string | undefined {
  if (!header) return undefined
  const extended = EXTENDED_NAME.exec(header)?.[1]
  const plain = PLAIN_NAME.exec(header)
  const raw = (extended && decodeExtended(extended)) ?? plain?.[1] ?? plain?.[2]?.trim()
  return raw?.split(/[\\/]/).pop() || undefined
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.hidden = true
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  // Revoking at once can cancel a download the browser has not started reading yet.
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS)
}

interface DownloadResult {
  data?: unknown
  error?: unknown
  response?: Response
}

/**
 * Saves what a generated-client call (made with `parseAs: 'blob'`) returned, under the name the
 * server proposed. Resolves false when the call failed: the API error interceptor has already
 * raised its toast with the server's message, so the caller has nothing more to report.
 */
export async function saveDownload(request: Promise<DownloadResult>, fallbackName: string): Promise<boolean> {
  const { data, error, response } = await request
  if (error !== undefined || !(data instanceof Blob)) return false
  saveBlob(data, filenameFromDisposition(response?.headers.get('Content-Disposition')) ?? fallbackName)
  return true
}
