import { ref } from 'vue'
import { client } from '@/api/client.gen'
import type { AnalysisCreated } from '@/api'
import { errorMessage } from '@/services/api-error'
import type { ImportSizeClass } from '@/services/import-limits'

export type ImportKind = 'pcap' | 'pcapng' | 'memory_image' | 'unsupported'
export type ImportFailure = 'too_large' | 'unsupported' | 'network' | 'failed'

const SNIFF_BYTES = 8
const CAPTURE_PATH = '/api/analyses/import'
const MEMORY_IMAGE_PATH = '/api/analyses/import/memory-image'
const HTTP_CREATED = 201
const HTTP_TOO_LARGE = 413
const HTTP_UNSUPPORTED_MEDIA_TYPE = 415

const ascii = (text: string): number[] => Array.from(text, (char) => char.charCodeAt(0))
const PCAP_MAGICS = [
  [0xa1, 0xb2, 0xc3, 0xd4],
  [0xd4, 0xc3, 0xb2, 0xa1],
  [0xa1, 0xb2, 0x3c, 0x4d],
  [0x4d, 0x3c, 0xb2, 0xa1],
]
const PCAPNG_MAGIC = [0x0a, 0x0d, 0x0d, 0x0a]
const MEMORY_IMAGE_MAGICS = [ascii('\x7fELF'), ascii('PAGEDU64'), ascii('PAGEDUMP')]

function startsWithMagic(head: Uint8Array, magic: number[]): boolean {
  return magic.length <= head.length && magic.every((byte, index) => head[index] === byte)
}

/** Guesses the import kind from the first bytes, with the same magics the backend's sniff uses. */
export function sniffImportKind(head: Uint8Array): ImportKind {
  if (PCAP_MAGICS.some((magic) => startsWithMagic(head, magic))) return 'pcap'
  if (startsWithMagic(head, PCAPNG_MAGIC)) return 'pcapng'
  if (MEMORY_IMAGE_MAGICS.some((magic) => startsWithMagic(head, magic))) return 'memory_image'
  return 'unsupported'
}

export async function readImportHead(file: File): Promise<Uint8Array> {
  return new Uint8Array(await file.slice(0, SNIFF_BYTES).arrayBuffer())
}

export function sizeClassOf(kind: ImportKind): ImportSizeClass | undefined {
  if (kind === 'pcap' || kind === 'pcapng') return 'capture'
  if (kind === 'memory_image') return 'memory_image'
  return undefined
}

export function importPathFor(kind: ImportKind): string | undefined {
  if (kind === 'pcap' || kind === 'pcapng') return CAPTURE_PATH
  if (kind === 'memory_image') return MEMORY_IMAGE_PATH
  return undefined
}

export class ImportUploadError extends Error {
  readonly failure: ImportFailure

  constructor(failure: ImportFailure, message: string) {
    super(message)
    this.name = 'ImportUploadError'
    this.failure = failure
  }
}

function failureOf(status: number, body: unknown): ImportUploadError {
  if (status === 0) return new ImportUploadError('network', 'network')
  if (status === HTTP_TOO_LARGE) return new ImportUploadError('too_large', errorMessage(body))
  if (status === HTTP_UNSUPPORTED_MEDIA_TYPE) return new ImportUploadError('unsupported', errorMessage(body))
  return new ImportUploadError('failed', errorMessage(body))
}

function parseBody(text: string): unknown {
  try {
    return JSON.parse(text) as unknown
  } catch {
    return undefined
  }
}

function postImport(
  path: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<AnalysisCreated> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', `${client.getConfig().baseUrl ?? ''}${path}`)
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    request.onerror = () => reject(failureOf(0, undefined))
    request.onload = () => {
      const body = parseBody(request.responseText)
      if (request.status === HTTP_CREATED) resolve(body as AnalysisCreated)
      else reject(failureOf(request.status, body))
    }
    const form = new FormData()
    form.append('file', file, file.name)
    request.send(form)
  })
}

/**
 * Uploads a capture or memory image with XHR, which the generated fetch client cannot report
 * progress for. The generated client's base URL is reused so the request goes where the rest does.
 */
export function useImportUpload() {
  const progress = ref(0)
  const uploading = ref(false)

  async function upload(file: File, kind: ImportKind): Promise<AnalysisCreated> {
    const path = importPathFor(kind)
    if (!path) throw new ImportUploadError('unsupported', 'unsupported')
    uploading.value = true
    progress.value = 0
    try {
      return await postImport(path, file, (fraction) => {
        progress.value = fraction
      })
    } finally {
      uploading.value = false
    }
  }

  return { progress, uploading, upload }
}
