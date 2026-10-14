import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify, Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { annotations, failed, noteAnnotation, succeeded } from './annotation-fixtures'

const annotationsReadMock = vi.fn()
const annotationsAddNoteMock = vi.fn()
const annotationsUpdateNoteMock = vi.fn()
const annotationsDeleteNoteMock = vi.fn()
vi.mock('@/api', () => ({
  annotationsRead: (...args: unknown[]) => annotationsReadMock(...args),
  annotationsAddNote: (...args: unknown[]) => annotationsAddNoteMock(...args),
  annotationsUpdateNote: (...args: unknown[]) => annotationsUpdateNoteMock(...args),
  annotationsDeleteNote: (...args: unknown[]) => annotationsDeleteNoteMock(...args),
}))

const { default: NoteEditor } = await import('@/components/NoteEditor.vue')
const { ANALYSIS_TARGET, processTarget, useAnnotationsStore } = await import('@/stores/annotations')
const { MAX_NOTE_LENGTH } = await import('@/services/note-body')

const SAVED = noteAnnotation({ body: 'First look' })

async function mountEditor(props: { target?: typeof ANALYSIS_TARGET; editable?: boolean } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  await useAnnotationsStore().ensureLoaded(45)
  const wrapper = mount(NoteEditor, {
    attachTo: document.body,
    global: { plugins: [Quasar, pinia] },
    props: { target: ANALYSIS_TARGET, label: 'Note', ...props },
  })
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountEditor>>

// Quasar reports a blur one timer tick after the focus really left the field.
const nextTick = () => new Promise((resolve) => setTimeout(resolve, 0))

async function leave(textarea: { element: HTMLTextAreaElement }) {
  textarea.element.blur()
  await nextTick()
  await flushPromises()
}

async function edit(wrapper: Wrapper, text: string, { blur = true } = {}) {
  const textarea = wrapper.get('textarea')
  textarea.element.focus()
  await textarea.setValue(text)
  if (blur) await leave(textarea)
  return textarea
}

beforeEach(() => {
  document.body.innerHTML = ''
  Notify.create = vi.fn()
  annotationsReadMock.mockReset().mockResolvedValue(succeeded(annotations([], [SAVED])))
  annotationsAddNoteMock.mockReset()
  annotationsUpdateNoteMock.mockReset()
  annotationsDeleteNoteMock.mockReset()
})

describe('NoteEditor', () => {
  it('shows the saved note of its target', async () => {
    const wrapper = await mountEditor()
    expect(wrapper.get('textarea').element.value).toBe('First look')
  })

  it('starts empty for a target without a note', async () => {
    const wrapper = await mountEditor({ target: processTarget(9708) })
    expect(wrapper.get('textarea').element.value).toBe('')
  })

  it('saves on blur and says so in a toast', async () => {
    const wrapper = await mountEditor()
    annotationsUpdateNoteMock.mockResolvedValue(succeeded({ ...SAVED, body: 'Second look' }))

    await edit(wrapper, 'Second look')

    expect(annotationsUpdateNoteMock).toHaveBeenCalledWith({ path: { note_id: SAVED.id }, body: { body: 'Second look' } })
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success', message: 'Note saved' }))
    expect(wrapper.get('.note-editor__status').text()).toBe('SAVED')
  })

  it('creates the note on the first text', async () => {
    const wrapper = await mountEditor({ target: processTarget(9708) })
    annotationsAddNoteMock.mockResolvedValue(
      succeeded(noteAnnotation({ target_type: 'process', target_ref: '9708', body: 'new' })),
    )
    await edit(wrapper, 'new')
    expect(annotationsAddNoteMock).toHaveBeenCalledWith({
      path: { analysis_id: 45 },
      body: { target_type: 'process', target_ref: '9708', body: 'new' },
    })
  })

  it('saves nothing when the text did not change', async () => {
    const wrapper = await mountEditor()
    const textarea = wrapper.get('textarea')
    textarea.element.focus()
    await leave(textarea)
    expect(annotationsUpdateNoteMock).not.toHaveBeenCalled()
    expect(Notify.create).not.toHaveBeenCalled()
  })

  it('deletes the note when it is cleared, and says it was removed', async () => {
    const wrapper = await mountEditor()
    annotationsDeleteNoteMock.mockResolvedValue({ data: undefined, error: undefined })
    await edit(wrapper, '')
    expect(annotationsDeleteNoteMock).toHaveBeenCalledWith({ path: { note_id: SAVED.id } })
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success', message: 'Note removed' }))
  })

  it('shows it is saving while the request is out', async () => {
    const wrapper = await mountEditor()
    annotationsUpdateNoteMock.mockReturnValue(new Promise(() => undefined))
    await edit(wrapper, 'Second look')
    expect(wrapper.get('.note-editor__status').text()).toBe('SAVING…')
  })

  it('keeps the draft and marks it not saved when the save fails, then retries on the next blur', async () => {
    const wrapper = await mountEditor()
    annotationsUpdateNoteMock.mockResolvedValue(failed('boom', 500))

    const textarea = await edit(wrapper, 'Second look')

    expect(textarea.element.value).toBe('Second look')
    expect(wrapper.get('.note-editor__status').text()).toBe('NOT SAVED')
    expect(wrapper.classes()).toContain('has-error')

    annotationsUpdateNoteMock.mockResolvedValue(succeeded({ ...SAVED, body: 'Second look' }))
    textarea.element.focus()
    await leave(textarea)
    expect(annotationsUpdateNoteMock).toHaveBeenCalledTimes(2)
    expect(wrapper.get('.note-editor__status').text()).toBe('SAVED')
  })

  it('counts the characters only near the limit', async () => {
    const wrapper = await mountEditor()
    await edit(wrapper, 'short', { blur: false })
    expect(wrapper.find('.note-editor__counter').exists()).toBe(false)

    await edit(wrapper, 'x'.repeat(MAX_NOTE_LENGTH - 100), { blur: false })
    expect(wrapper.get('.note-editor__counter').text()).toBe('19,900 / 20,000')
  })

  it('stops typing at the limit', async () => {
    const wrapper = await mountEditor()
    expect(wrapper.get('textarea').attributes('maxlength')).toBe(String(MAX_NOTE_LENGTH))
  })

  it('shows the note as plain text and offers no field when it is read-only', async () => {
    const wrapper = await mountEditor({ editable: false })
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.get('.note-editor__text').text()).toBe('First look')
  })

  it('shows nothing for a read-only target without a note', async () => {
    const wrapper = await mountEditor({ editable: false, target: processTarget(1) })
    expect(wrapper.find('.note-editor__text').exists()).toBe(false)
    expect(wrapper.text()).toContain('no note')
  })
})
