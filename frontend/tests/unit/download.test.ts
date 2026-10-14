import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { filenameFromDisposition, saveDownload } from '@/services/download'

const BLOB = new Blob(['a,b\n1,2\n'], { type: 'text/csv' })

function responseWith(disposition?: string): Response {
  return new Response(null, { headers: disposition ? { 'Content-Disposition': disposition } : {} })
}

describe('filenameFromDisposition', () => {
  it.each([
    ['a quoted name', 'attachment; filename="iocs-193.csv"', 'iocs-193.csv'],
    ['a bare name', 'attachment; filename=report.pdf', 'report.pdf'],
    ['an extended name, decoded', "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.html", 'résumé.html'],
    ['the extended name over the plain one', 'attachment; filename="x.html"; filename*=UTF-8\'\'real.html', 'real.html'],
  ])('reads %s', (_label, header, expected) => {
    expect(filenameFromDisposition(header)).toBe(expected)
  })

  it.each([[undefined], [null], ['attachment'], ['inline; filename=""']])('finds nothing in %s', (header) => {
    expect(filenameFromDisposition(header)).toBeUndefined()
  })

  it('keeps a path out of the name', () => {
    expect(filenameFromDisposition('attachment; filename="../../etc/passwd"')).toBe('passwd')
  })
})

describe('saveDownload', () => {
  let clicked: HTMLAnchorElement[]
  const createObjectURL = vi.fn(() => 'blob:tartarus/1')
  const revokeObjectURL = vi.fn()

  beforeEach(() => {
    clicked = []
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL }))
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this)
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('saves the blob under the name the server gave', async () => {
    const saved = await saveDownload(
      Promise.resolve({ data: BLOB, response: responseWith('attachment; filename="iocs-193.csv"') }),
      'fallback.bin',
    )

    expect(saved).toBe(true)
    expect(createObjectURL).toHaveBeenCalledWith(BLOB)
    expect(clicked).toHaveLength(1)
    expect(clicked[0]!.download).toBe('iocs-193.csv')
    expect(clicked[0]!.href).toBe('blob:tartarus/1')
  })

  it('falls back to the given name when the server named nothing', async () => {
    await saveDownload(Promise.resolve({ data: BLOB, response: responseWith() }), 'iocs-193.csv')
    expect(clicked[0]!.download).toBe('iocs-193.csv')
  })

  it('releases the object URL once the click is handed to the browser, and leaves no anchor behind', async () => {
    vi.useFakeTimers()
    await saveDownload(Promise.resolve({ data: BLOB, response: responseWith() }), 'x.csv')
    expect(document.querySelector('a[download]')).toBeNull()
    await vi.runAllTimersAsync()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:tartarus/1')
    vi.useRealTimers()
  })

  it('saves nothing and says so when the request failed', async () => {
    const saved = await saveDownload(Promise.resolve({ error: { error: { message: 'nope' } }, response: responseWith() }), 'x.csv')

    expect(saved).toBe(false)
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(clicked).toEqual([])
  })
})
