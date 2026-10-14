import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { annotations, failed, noteAnnotation, succeeded, tagAnnotation } from './annotation-fixtures'

const annotationsReadMock = vi.fn()
vi.mock('@/api', () => ({
  annotationsRead: (...args: unknown[]) => annotationsReadMock(...args),
}))

const { default: TargetAnnotations } = await import('@/components/TargetAnnotations.vue')
const { default: NoteEditor } = await import('@/components/NoteEditor.vue')
const { default: TagInput } = await import('@/components/TagInput.vue')
const { eventTarget, useAnnotationsStore } = await import('@/stores/annotations')

const TARGET = eventTarget('evt-1')

async function mountSection(props: { editable?: boolean; hint?: string } = {}, load = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAnnotationsStore()
  if (load) await store.ensureLoaded(45)
  const wrapper = mount(TargetAnnotations, { global: { plugins: [Quasar, pinia] }, props: { target: TARGET, ...props } })
  await flushPromises()
  return { wrapper, store }
}

beforeEach(() => {
  annotationsReadMock.mockReset().mockResolvedValue(
    succeeded(
      annotations(
        [tagAnnotation({ tag: 'c2', target_type: 'event', target_ref: 'evt-1' })],
        [noteAnnotation({ target_type: 'event', target_ref: 'evt-1', body: 'Beacon to the C2' })],
      ),
    ),
  )
})

describe('TargetAnnotations', () => {
  it('has a tag input and a note editor for its target', async () => {
    const { wrapper } = await mountSection()
    expect(wrapper.get('h4').text()).toBe('TAGS AND NOTE')
    expect(wrapper.findComponent(TagInput).props()).toMatchObject({ target: TARGET, editable: true })
    expect(wrapper.findComponent(NoteEditor).props()).toMatchObject({ target: TARGET, editable: true })
  })

  it('shows what exists but offers no controls, with the reason, when it cannot be edited', async () => {
    const { wrapper } = await mountSection({ editable: false, hint: 'events can be annotated once the analysis is finished' })
    expect(wrapper.findComponent(TagInput).props('editable')).toBe(false)
    expect(wrapper.findComponent(NoteEditor).props('editable')).toBe(false)
    expect(wrapper.get('.target-annotations__hint').text()).toBe('events can be annotated once the analysis is finished')
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.find('.tag-input__add').exists()).toBe(false)
  })

  it('shows no hint while it can be edited', async () => {
    const { wrapper } = await mountSection({ hint: 'ignored' })
    expect(wrapper.find('.target-annotations__hint').exists()).toBe(false)
  })

  it('shows a skeleton while the annotations load', async () => {
    annotationsReadMock.mockReturnValue(new Promise(() => undefined))
    const pinia = createPinia()
    setActivePinia(pinia)
    void useAnnotationsStore().ensureLoaded(45)
    const wrapper = mount(TargetAnnotations, { global: { plugins: [Quasar, pinia] }, props: { target: TARGET } })
    expect(wrapper.find('.skeleton').exists()).toBe(true)
    expect(wrapper.findComponent(TagInput).exists()).toBe(false)
  })

  it('shows the failure and reads again on retry', async () => {
    annotationsReadMock.mockResolvedValue(failed('index is down', 500))
    const { wrapper } = await mountSection()
    expect(wrapper.text()).toContain('failed to load: index is down')

    annotationsReadMock.mockResolvedValue(succeeded(annotations()))
    await wrapper.get('.retry-btn').trigger('click')
    await flushPromises()
    expect(wrapper.findComponent(TagInput).exists()).toBe(true)
  })
})
