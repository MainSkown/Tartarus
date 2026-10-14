import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify, Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { annotations, failed, succeeded, tagAnnotation } from './annotation-fixtures'

const annotationsReadMock = vi.fn()
const annotationsAddTagMock = vi.fn()
const annotationsRemoveTagMock = vi.fn()
const annotationsListTagsMock = vi.fn()
vi.mock('@/api', () => ({
  annotationsRead: (...args: unknown[]) => annotationsReadMock(...args),
  annotationsAddTag: (...args: unknown[]) => annotationsAddTagMock(...args),
  annotationsRemoveTag: (...args: unknown[]) => annotationsRemoveTagMock(...args),
  annotationsListTags: (...args: unknown[]) => annotationsListTagsMock(...args),
}))

const { default: TagInput } = await import('@/components/TagInput.vue')
const { ANALYSIS_TARGET, processTarget, useAnnotationsStore } = await import('@/stores/annotations')

const EXISTING = tagAnnotation({ tag: 'phishing' })
const USAGE = [
  { name: 'phishing', count: 7 },
  { name: 'emotet', count: 3 },
  { name: 'needs-review', count: 1 },
]

async function mountInput(props: { target?: typeof ANALYSIS_TARGET; editable?: boolean } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  await useAnnotationsStore().ensureLoaded(45)
  const wrapper = mount(TagInput, {
    attachTo: document.body,
    // The popover is teleported to the body in the app; rendered in place it can be queried through the wrapper.
    global: { plugins: [Quasar, pinia], stubs: { teleport: true } },
    props: { target: ANALYSIS_TARGET, editable: true, ...props },
  })
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountInput>>

async function openInput(wrapper: Wrapper) {
  await wrapper.get('.tag-input__add').trigger('click')
  await flushPromises()
  return wrapper.get<HTMLInputElement>('.tag-input__field')
}

async function type(wrapper: Wrapper, text: string) {
  const input = wrapper.get<HTMLInputElement>('.tag-input__field')
  await input.setValue(text)
  return input
}

const chipNames = (wrapper: Wrapper) => wrapper.findAll('.tag-chip').map((chip) => chip.attributes('title'))

beforeEach(() => {
  document.body.innerHTML = ''
  Notify.create = vi.fn()
  annotationsReadMock.mockReset().mockResolvedValue(succeeded(annotations([EXISTING])))
  annotationsAddTagMock.mockReset()
  annotationsRemoveTagMock.mockReset()
  annotationsListTagsMock.mockReset().mockResolvedValue(succeeded(USAGE))
})

describe('TagInput chips', () => {
  it('shows the tags of its target only', async () => {
    annotationsReadMock.mockResolvedValue(
      succeeded(annotations([EXISTING, tagAnnotation({ tag: 'dropper', target_type: 'process', target_ref: '9708' })])),
    )
    expect(chipNames(await mountInput())).toEqual(['phishing'])
    expect(chipNames(await mountInput({ target: processTarget(9708) }))).toEqual(['dropper'])
  })

  it('removes a tag from its chip', async () => {
    const wrapper = await mountInput()
    annotationsRemoveTagMock.mockResolvedValue({ data: undefined, error: undefined })

    await wrapper.get('.tag-chip__remove').trigger('click')
    await flushPromises()

    expect(annotationsRemoveTagMock).toHaveBeenCalledWith({ path: { analysis_id: 45, link_id: EXISTING.link_id } })
    expect(chipNames(wrapper)).toEqual([])
  })

  it('toasts and keeps the chip when the tag cannot be removed', async () => {
    const wrapper = await mountInput()
    annotationsRemoveTagMock.mockResolvedValue(failed('boom', 500))

    await wrapper.get('.tag-chip__remove').trigger('click')
    await flushPromises()

    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-error' }))
    expect(chipNames(wrapper)).toEqual(['phishing'])
  })

  it('offers no add button and no remove buttons when it is read-only', async () => {
    const wrapper = await mountInput({ editable: false })
    expect(chipNames(wrapper)).toEqual(['phishing'])
    expect(wrapper.find('.tag-input__add').exists()).toBe(false)
    expect(wrapper.find('.tag-chip__remove').exists()).toBe(false)
  })
})

describe('TagInput adding', () => {
  it('opens a focused input from the plus button and reads the tags in use for suggestions', async () => {
    const wrapper = await mountInput()
    expect(wrapper.find('.tag-input__field').exists()).toBe(false)

    const input = await openInput(wrapper)

    expect(document.activeElement).toBe(input.element)
    expect(annotationsListTagsMock).toHaveBeenCalledTimes(1)
  })

  it('adds the typed name on Enter, lower-cased, and clears the field for the next one', async () => {
    const wrapper = await mountInput()
    annotationsAddTagMock.mockResolvedValue(succeeded(tagAnnotation({ tag: 'emotet' })))
    await openInput(wrapper)
    const input = await type(wrapper, ' Emotet ')

    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(annotationsAddTagMock).toHaveBeenCalledWith(
      expect.objectContaining({ body: { target_type: 'analysis', target_ref: '', tag: 'emotet' } }),
    )
    expect(chipNames(wrapper)).toEqual(['phishing', 'emotet'])
    expect(input.element.value).toBe('')
    expect(wrapper.find('.tag-input__message').exists()).toBe(false)
  })

  it('shows what is wrong with a name while it is typed and does not send it', async () => {
    const wrapper = await mountInput()
    const input = await (async () => {
      await openInput(wrapper)
      return type(wrapper, 'bad name!')
    })()

    expect(wrapper.get('.tag-input__message').text()).toBe("only a-z, 0-9, '.', '_' and '-'")
    expect(input.classes()).toContain('is-invalid')

    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(annotationsAddTagMock).not.toHaveBeenCalled()
  })

  it('says a tag is already on the target as soon as it is typed', async () => {
    const wrapper = await mountInput()
    await openInput(wrapper)
    await type(wrapper, 'phishing')
    expect(wrapper.get('.tag-input__message').text()).toBe('already on this target')
  })

  it('shows the message of a tag the server refuses, and clears it when the text changes', async () => {
    const wrapper = await mountInput()
    annotationsAddTagMock.mockResolvedValue(failed('Tag emotet is already on this target', 409))
    await openInput(wrapper)
    const input = await type(wrapper, 'emotet')

    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.get('.tag-input__message').text()).toBe('Tag emotet is already on this target')
    expect(input.element.value).toBe('emotet')

    await type(wrapper, 'emotet2')
    expect(wrapper.find('.tag-input__message').exists()).toBe(false)
  })

  it('does nothing on Enter in an empty field', async () => {
    const wrapper = await mountInput()
    const input = await openInput(wrapper)
    await input.trigger('keydown', { key: 'Enter' })
    expect(annotationsAddTagMock).not.toHaveBeenCalled()
    expect(wrapper.find('.tag-input__message').exists()).toBe(false)
  })

  it('closes the field on Escape', async () => {
    const wrapper = await mountInput()
    const input = await openInput(wrapper)
    await input.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('.tag-input__field').exists()).toBe(false)
  })
})

describe('TagInput suggestions', () => {
  it('lists the tags in use with their counts, minus the ones the target has', async () => {
    const wrapper = await mountInput()
    await openInput(wrapper)
    const options = wrapper.findAll('.tag-input__option')
    expect(options.map((option) => option.get('.tag-input__option-name').text())).toEqual(['emotet', 'needs-review'])
    expect(options.map((option) => option.get('.tag-input__option-count').text())).toEqual(['3', '1'])
  })

  it('narrows the list to the typed text', async () => {
    const wrapper = await mountInput()
    await openInput(wrapper)
    await type(wrapper, 'NEED')
    expect(wrapper.findAll('.tag-input__option').map((option) => option.text())).toEqual([expect.stringContaining('needs-review')])
  })

  it('adds a suggestion when it is clicked', async () => {
    const wrapper = await mountInput()
    annotationsAddTagMock.mockResolvedValue(succeeded(tagAnnotation({ tag: 'emotet' })))
    await openInput(wrapper)

    await wrapper.get('.tag-input__option').trigger('mousedown')
    await flushPromises()

    expect(annotationsAddTagMock).toHaveBeenCalledWith(expect.objectContaining({ body: expect.objectContaining({ tag: 'emotet' }) }))
  })

  it('walks the suggestions with the arrow keys and adds the highlighted one on Enter', async () => {
    const wrapper = await mountInput()
    annotationsAddTagMock.mockResolvedValue(succeeded(tagAnnotation({ tag: 'needs-review' })))
    const input = await openInput(wrapper)

    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.findAll('.tag-input__option')[1]!.attributes('aria-selected')).toBe('true')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(annotationsAddTagMock).toHaveBeenCalledWith(expect.objectContaining({ body: expect.objectContaining({ tag: 'needs-review' }) }))
  })

  it('still works when the tags in use cannot be read', async () => {
    annotationsListTagsMock.mockResolvedValue(failed('down', 500))
    const wrapper = await mountInput()
    annotationsAddTagMock.mockResolvedValue(succeeded(tagAnnotation({ tag: 'x' })))
    const input = await openInput(wrapper)
    expect(wrapper.find('.tag-input__option').exists()).toBe(false)

    await type(wrapper, 'x')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(annotationsAddTagMock).toHaveBeenCalled()
  })
})
