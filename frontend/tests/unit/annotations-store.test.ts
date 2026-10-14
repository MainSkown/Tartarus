import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { annotations, failed, noteAnnotation, succeeded, tagAnnotation } from './annotation-fixtures'

const annotationsReadMock = vi.fn()
const annotationsAddTagMock = vi.fn()
const annotationsRemoveTagMock = vi.fn()
const annotationsAddNoteMock = vi.fn()
const annotationsUpdateNoteMock = vi.fn()
const annotationsDeleteNoteMock = vi.fn()
vi.mock('@/api', () => ({
  annotationsRead: (...args: unknown[]) => annotationsReadMock(...args),
  annotationsAddTag: (...args: unknown[]) => annotationsAddTagMock(...args),
  annotationsRemoveTag: (...args: unknown[]) => annotationsRemoveTagMock(...args),
  annotationsAddNote: (...args: unknown[]) => annotationsAddNoteMock(...args),
  annotationsUpdateNote: (...args: unknown[]) => annotationsUpdateNoteMock(...args),
  annotationsDeleteNote: (...args: unknown[]) => annotationsDeleteNoteMock(...args),
}))

const { ANALYSIS_TARGET, eventTarget, processTarget, useAnnotationsStore } = await import('@/stores/annotations')
const { useAnalysesStore } = await import('@/stores/analyses')
const { quietOn } = await import('@/services/quiet-statuses')

const PROCESS_TAG = tagAnnotation({ tag: 'dropper', target_type: 'process', target_ref: '9708' })
const ANALYSIS_TAG = tagAnnotation({ tag: 'phishing' })
const EVENT_NOTE = noteAnnotation({ target_type: 'event', target_ref: 'abc', body: 'C2 beacon' })
const ANALYSIS_NOTE = noteAnnotation({ body: 'First look' })

async function loadedStore(content = annotations([ANALYSIS_TAG, PROCESS_TAG], [ANALYSIS_NOTE, EVENT_NOTE])) {
  annotationsReadMock.mockResolvedValue(succeeded(content))
  const store = useAnnotationsStore()
  await store.ensureLoaded(45)
  return store
}

beforeEach(() => {
  setActivePinia(createPinia())
  for (const mock of [
    annotationsReadMock,
    annotationsAddTagMock,
    annotationsRemoveTagMock,
    annotationsAddNoteMock,
    annotationsUpdateNoteMock,
    annotationsDeleteNoteMock,
  ]) {
    mock.mockReset()
  }
})

describe('annotations store: loading', () => {
  it('reads every annotation of the analysis once', async () => {
    const store = await loadedStore()
    expect(annotationsReadMock).toHaveBeenCalledWith({ path: { analysis_id: 45 } })
    expect(store.tags).toHaveLength(2)
    expect(store.notes).toHaveLength(2)
    expect(store.loadError).toBeUndefined()
  })

  it('does not read again for the analysis it already holds', async () => {
    const store = await loadedStore()
    await store.ensureLoaded(45)
    expect(annotationsReadMock).toHaveBeenCalledTimes(1)
  })

  it('shares one read between callers that ask while it is in flight', async () => {
    annotationsReadMock.mockResolvedValue(succeeded(annotations()))
    const store = useAnnotationsStore()
    await Promise.all([store.ensureLoaded(45), store.ensureLoaded(45)])
    expect(annotationsReadMock).toHaveBeenCalledTimes(1)
  })

  it('drops what it held when another analysis is asked for', async () => {
    const store = await loadedStore()
    annotationsReadMock.mockResolvedValue(succeeded(annotations()))
    await store.ensureLoaded(46)
    expect(annotationsReadMock).toHaveBeenLastCalledWith({ path: { analysis_id: 46 } })
    expect(store.tags).toEqual([])
  })

  it('keeps the message of a failed read and reads again on reload', async () => {
    annotationsReadMock.mockResolvedValue(failed('index is down', 500))
    const store = useAnnotationsStore()
    await store.ensureLoaded(45)
    expect(store.loadError).toBe('index is down')

    annotationsReadMock.mockResolvedValue(succeeded(annotations([ANALYSIS_TAG])))
    await store.reload()
    expect(store.loadError).toBeUndefined()
    expect(store.tags).toHaveLength(1)
  })

  it('reads again on reload even when nothing failed', async () => {
    const store = await loadedStore()
    annotationsReadMock.mockResolvedValue(succeeded(annotations([ANALYSIS_TAG])))
    await store.reload()
    expect(annotationsReadMock).toHaveBeenCalledTimes(2)
    expect(store.tags).toEqual([ANALYSIS_TAG])
  })

  it('has nothing to reload before an analysis was asked for', async () => {
    await useAnnotationsStore().reload()
    expect(annotationsReadMock).not.toHaveBeenCalled()
  })

  it('retries a failed analysis when it is asked for again', async () => {
    annotationsReadMock.mockResolvedValueOnce(failed('boom', 500))
    const store = useAnnotationsStore()
    await store.ensureLoaded(45)
    annotationsReadMock.mockResolvedValue(succeeded(annotations()))
    await store.ensureLoaded(45)
    expect(annotationsReadMock).toHaveBeenCalledTimes(2)
  })
})

describe('annotations store: reading a target', () => {
  it('tells the tags and the note of each target apart', async () => {
    const store = await loadedStore()
    expect(store.tagsOf(ANALYSIS_TARGET).map((tag) => tag.tag)).toEqual(['phishing'])
    expect(store.tagsOf(processTarget(9708)).map((tag) => tag.tag)).toEqual(['dropper'])
    expect(store.tagsOf(processTarget(1))).toEqual([])
    expect(store.noteOf(ANALYSIS_TARGET)?.body).toBe('First look')
    expect(store.noteOf(eventTarget('abc'))?.body).toBe('C2 beacon')
    expect(store.noteOf(eventTarget('zzz'))).toBeUndefined()
  })
})

describe('annotations store: tags', () => {
  it('adds a tag and quiets the two statuses the editor shows inline', async () => {
    const store = await loadedStore(annotations())
    const added = tagAnnotation({ tag: 'emotet', target_type: 'process', target_ref: '9708' })
    annotationsAddTagMock.mockResolvedValue(succeeded(added))

    expect(await store.addTag(processTarget(9708), 'emotet')).toBeUndefined()

    expect(annotationsAddTagMock).toHaveBeenCalledWith({
      path: { analysis_id: 45 },
      body: { target_type: 'process', target_ref: '9708', tag: 'emotet' },
      meta: quietOn(409, 422),
    })
    expect(store.tagsOf(processTarget(9708))).toEqual([added])
  })

  it('refuses a duplicate on the target without asking the server', async () => {
    const store = await loadedStore()
    expect(await store.addTag(ANALYSIS_TARGET, 'phishing')).toBe('already on this target')
    expect(annotationsAddTagMock).not.toHaveBeenCalled()
  })

  it('gives back the server message of a refused tag and adds nothing', async () => {
    const store = await loadedStore(annotations())
    annotationsAddTagMock.mockResolvedValue(failed('Tag emotet is already on this target', 409))
    expect(await store.addTag(ANALYSIS_TARGET, 'emotet')).toBe('Tag emotet is already on this target')
    expect(store.tags).toEqual([])
  })

  it('prefers the first field message of a 422', async () => {
    const store = await loadedStore(annotations())
    annotationsAddTagMock.mockResolvedValue(
      failed('Request validation failed', 422, { fields: [{ location: ['body', 'tag'], message: 'bad tag' }] }),
    )
    expect(await store.addTag(ANALYSIS_TARGET, 'x')).toBe('bad tag')
  })

  it('removes a tag by its link id', async () => {
    const store = await loadedStore()
    annotationsRemoveTagMock.mockResolvedValue({ data: undefined, error: undefined })
    expect(await store.removeTag(PROCESS_TAG.link_id)).toBe(true)
    expect(annotationsRemoveTagMock).toHaveBeenCalledWith({ path: { analysis_id: 45, link_id: PROCESS_TAG.link_id } })
    expect(store.tagsOf(processTarget(9708))).toEqual([])
  })

  it('keeps a tag the server would not remove', async () => {
    const store = await loadedStore()
    annotationsRemoveTagMock.mockResolvedValue(failed('gone', 404))
    expect(await store.removeTag(PROCESS_TAG.link_id)).toBe(false)
    expect(store.tagsOf(processTarget(9708))).toHaveLength(1)
  })

  it('tells the analyses store the analysis tags, so the Dashboard row matches', async () => {
    const store = await loadedStore(annotations())
    const analyses = useAnalysesStore()
    const setTags = vi.spyOn(analyses, 'setTags')
    annotationsAddTagMock.mockResolvedValue(succeeded(tagAnnotation({ tag: 'b' })))
    await store.addTag(ANALYSIS_TARGET, 'b')
    expect(setTags).toHaveBeenLastCalledWith(45, ['b'])

    annotationsAddTagMock.mockResolvedValue(succeeded(tagAnnotation({ tag: 'a' })))
    await store.addTag(ANALYSIS_TARGET, 'a')
    expect(setTags).toHaveBeenLastCalledWith(45, ['a', 'b'])
  })

  it('leaves the analyses store alone for a process tag', async () => {
    const store = await loadedStore(annotations())
    const setTags = vi.spyOn(useAnalysesStore(), 'setTags')
    annotationsAddTagMock.mockResolvedValue(succeeded(tagAnnotation({ target_type: 'process', target_ref: '1' })))
    await store.addTag(processTarget(1), 'x')
    expect(setTags).not.toHaveBeenCalled()
  })
})

describe('annotations store: notes', () => {
  it('adds a note when the target has none', async () => {
    const store = await loadedStore(annotations())
    const added = noteAnnotation({ target_type: 'process', target_ref: '9708', body: 'persists via Run key' })
    annotationsAddNoteMock.mockResolvedValue(succeeded(added))

    expect(await store.saveNote(processTarget(9708), 'persists via Run key')).toBe(true)

    expect(annotationsAddNoteMock).toHaveBeenCalledWith({
      path: { analysis_id: 45 },
      body: { target_type: 'process', target_ref: '9708', body: 'persists via Run key' },
    })
    expect(store.noteOf(processTarget(9708))).toEqual(added)
  })

  it('replaces the text of the note the target has', async () => {
    const store = await loadedStore()
    annotationsUpdateNoteMock.mockResolvedValue(succeeded({ ...ANALYSIS_NOTE, body: 'Second look' }))

    expect(await store.saveNote(ANALYSIS_TARGET, 'Second look')).toBe(true)

    expect(annotationsUpdateNoteMock).toHaveBeenCalledWith({ path: { note_id: ANALYSIS_NOTE.id }, body: { body: 'Second look' } })
    expect(store.noteOf(ANALYSIS_TARGET)?.body).toBe('Second look')
    expect(store.notes).toHaveLength(2)
  })

  it('deletes the note when its text is cleared', async () => {
    const store = await loadedStore()
    annotationsDeleteNoteMock.mockResolvedValue({ data: undefined, error: undefined })

    expect(await store.saveNote(ANALYSIS_TARGET, '  \n ')).toBe(true)

    expect(annotationsDeleteNoteMock).toHaveBeenCalledWith({ path: { note_id: ANALYSIS_NOTE.id } })
    expect(store.noteOf(ANALYSIS_TARGET)).toBeUndefined()
  })

  it('has nothing to do for a cleared note that was never saved', async () => {
    const store = await loadedStore(annotations())
    expect(await store.saveNote(ANALYSIS_TARGET, '')).toBe(true)
    expect(annotationsAddNoteMock).not.toHaveBeenCalled()
    expect(annotationsDeleteNoteMock).not.toHaveBeenCalled()
  })

  it('keeps the old text when the server refuses the new one', async () => {
    const store = await loadedStore()
    annotationsUpdateNoteMock.mockResolvedValue(failed('boom', 500))
    expect(await store.saveNote(ANALYSIS_TARGET, 'Second look')).toBe(false)
    expect(store.noteOf(ANALYSIS_TARGET)?.body).toBe('First look')
  })

  it('deletes a note by id', async () => {
    const store = await loadedStore()
    annotationsDeleteNoteMock.mockResolvedValue({ data: undefined, error: undefined })
    expect(await store.deleteNote(EVENT_NOTE.id)).toBe(true)
    expect(store.noteOf(eventTarget('abc'))).toBeUndefined()
  })
})
