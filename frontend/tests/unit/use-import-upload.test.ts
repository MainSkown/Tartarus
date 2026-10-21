import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisCreated } from '@/api'
import {
  ImportUploadError,
  importPathFor,
  readImportHead,
  sniffImportKind,
  useImportUpload,
} from '@/composables/use-import-upload'

const CAPTURE_PATH = '/api/analyses/import'
const MEMORY_PATH = '/api/analyses/import/memory-image'

function bytesOf(...values: number[]): Uint8Array {
  return Uint8Array.from(values)
}

function asciiBytes(text: string): Uint8Array {
  return Uint8Array.from(text, (char) => char.charCodeAt(0))
}

describe('sniffImportKind', () => {
  it.each([
    ['pcap, big-endian', bytesOf(0xa1, 0xb2, 0xc3, 0xd4, 0, 0), 'pcap'],
    ['pcap, little-endian', bytesOf(0xd4, 0xc3, 0xb2, 0xa1, 0, 0), 'pcap'],
    ['pcap, nanosecond big-endian', bytesOf(0xa1, 0xb2, 0x3c, 0x4d, 0, 0), 'pcap'],
    ['pcap, nanosecond little-endian', bytesOf(0x4d, 0x3c, 0xb2, 0xa1, 0, 0), 'pcap'],
    ['pcapng section header', bytesOf(0x0a, 0x0d, 0x0d, 0x0a, 0, 0), 'pcapng'],
    ['ELF core', asciiBytes('\x7fELF\x02\x01'), 'memory_image'],
    ['crash dump, 64-bit', asciiBytes('PAGEDU64'), 'memory_image'],
    ['crash dump, 32-bit', asciiBytes('PAGEDUMP'), 'memory_image'],
    ['plain text', asciiBytes('hello world'), 'unsupported'],
    ['a truncated magic', bytesOf(0xa1, 0xb2), 'unsupported'],
    ['an empty head', bytesOf(), 'unsupported'],
  ])('recognises %s', (_name, head, expected) => {
    expect(sniffImportKind(head)).toBe(expected)
  })
})

describe('importPathFor', () => {
  it('sends captures to the capture path and memory images to the memory-image path', () => {
    expect(importPathFor('pcap')).toBe(CAPTURE_PATH)
    expect(importPathFor('pcapng')).toBe(CAPTURE_PATH)
    expect(importPathFor('memory_image')).toBe(MEMORY_PATH)
    expect(importPathFor('unsupported')).toBeUndefined()
  })
})

describe('readImportHead', () => {
  it('reads the first bytes of the file', async () => {
    const file = new File([new Uint8Array([0x0a, 0x0d, 0x0d, 0x0a, 1, 2, 3, 4, 5, 6])], 'x.pcapng')
    expect(Array.from(await readImportHead(file))).toEqual([0x0a, 0x0d, 0x0d, 0x0a, 1, 2, 3, 4])
  })
})

class FakeXhr {
  static last: FakeXhr | undefined
  method = ''
  url = ''
  body: unknown
  status = 0
  responseText = ''
  upload: { onprogress?: (event: { lengthComputable: boolean; loaded: number; total: number }) => void } = {}
  onload?: () => void
  onerror?: () => void

  constructor() {
    FakeXhr.last = this
  }

  open(method: string, url: string): void {
    this.method = method
    this.url = url
  }

  send(body: unknown): void {
    this.body = body
  }

  respond(status: number, body: unknown = {}): void {
    this.status = status
    this.responseText = JSON.stringify(body)
    this.onload?.()
  }
}

const CREATED = { id: 9, sample_sha256: 'ab', filename: 'trace.pcap', status: 'queued' } as unknown as AnalysisCreated

function fakeRequest(): FakeXhr {
  if (!FakeXhr.last) throw new Error('no upload was started')
  return FakeXhr.last
}

async function startUpload(kind: Parameters<ReturnType<typeof useImportUpload>['upload']>[1]) {
  const upload = useImportUpload()
  const file = new File(['payload'], 'trace.pcap')
  const pending = upload.upload(file, kind)
  return { upload, pending, request: fakeRequest() }
}

describe('useImportUpload', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    FakeXhr.last = undefined
  })

  beforeEach(() => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
  })

  it('posts a capture as multipart to the capture path and resolves with the created analysis', async () => {
    const { pending, request } = await startUpload('pcap')
    expect(request.method).toBe('POST')
    expect(request.url.endsWith(CAPTURE_PATH)).toBe(true)
    expect(request.body).toBeInstanceOf(FormData)
    expect((request.body as FormData).get('file')).toBeInstanceOf(File)
    request.respond(201, CREATED)
    await expect(pending).resolves.toEqual(CREATED)
  })

  it('posts a memory image to the memory-image path', async () => {
    const { request, pending } = await startUpload('memory_image')
    expect(request.url.endsWith(MEMORY_PATH)).toBe(true)
    request.respond(201, CREATED)
    await pending
  })

  it('reports the fraction uploaded and clears progress when done', async () => {
    const { upload, request, pending } = await startUpload('pcap')
    expect(upload.uploading.value).toBe(true)
    request.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 })
    expect(upload.progress.value).toBe(0.25)
    request.respond(201, CREATED)
    await pending
    expect(upload.uploading.value).toBe(false)
  })

  it.each([
    [413, 'too_large'],
    [415, 'unsupported'],
  ] as const)('maps HTTP %i to %s', async (status, failure) => {
    const { request, pending } = await startUpload('pcap')
    request.respond(status, { error: { code: 'x', message: 'refused by backend' } })
    const error = await pending.catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ImportUploadError)
    expect((error as ImportUploadError).failure).toBe(failure)
  })

  it('maps any other status to failed, keeping the backend message', async () => {
    const { request, pending } = await startUpload('pcap')
    request.respond(500, { error: { code: 'boom', message: 'disk full' } })
    const error = (await pending.catch((caught: unknown) => caught)) as ImportUploadError
    expect(error.failure).toBe('failed')
    expect(error.message).toBe('disk full')
  })

  it('maps a network failure to network', async () => {
    const { request, pending } = await startUpload('pcap')
    request.onerror?.()
    const error = (await pending.catch((caught: unknown) => caught)) as ImportUploadError
    expect(error.failure).toBe('network')
  })

  it('rejects an unsupported kind without sending anything', async () => {
    const upload = useImportUpload()
    await expect(upload.upload(new File(['x'], 'x.bin'), 'unsupported')).rejects.toMatchObject({
      failure: 'unsupported',
    })
    expect(FakeXhr.last).toBeUndefined()
  })
})
