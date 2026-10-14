import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FieldRead } from '@/api'
import { QUERY_EXAMPLES } from '@/services/query-examples'

const queryFieldsMock = vi.fn()
const queryValuesMock = vi.fn()
const queryValidateMock = vi.fn()
vi.mock('@/api', () => ({
  queryFields: (...args: unknown[]) => queryFieldsMock(...args),
  queryValues: (...args: unknown[]) => queryValuesMock(...args),
  queryValidate: (...args: unknown[]) => queryValidateMock(...args),
}))

const { default: QueryBar } = await import('@/components/QueryBar.vue')
const { useQueryStateStore } = await import('@/stores/query-state')
const { SUGGESTION_DELAY_MS } = await import('@/composables/use-query-suggestions')
const { VALIDATION_DELAY_MS } = await import('@/composables/use-query-validation')

function field(overrides: Partial<FieldRead> & Pick<FieldRead, 'name'>): FieldRead {
  return { type: 'keyword', aliases: [], description: '', example: '', lane: null, members: [], searchable: true, ...overrides }
}

const CATALOG = [
  field({ name: 'process.name', aliases: ['proc', 'process'], example: 'cmd.exe' }),
  field({ name: 'process.pid', type: 'long', aliases: ['pid'], example: '4120' }),
  field({ name: 'file.path', type: 'keyword_with_text', aliases: ['path'] }),
]

const UNKNOWN_FIELD_MESSAGE = "unknown field 'prcss'; did you mean 'process'?"

let store: ReturnType<typeof useQueryStateStore>
const mounted: VueWrapper[] = []

function mountBar(applied = ''): VueWrapper {
  const pinia = createPinia()
  setActivePinia(pinia)
  store = useQueryStateStore()
  store.setText(applied)
  const wrapper = mount(QueryBar, { props: { analysisId: 7 }, global: { plugins: [Quasar, pinia] }, attachTo: document.body })
  mounted.push(wrapper)
  return wrapper
}

const inputOf = (wrapper: VueWrapper) => wrapper.find('input.query-bar__input')
const inputElement = (wrapper: VueWrapper) => inputOf(wrapper).element as HTMLInputElement

async function type(wrapper: VueWrapper, text: string): Promise<void> {
  const input = inputOf(wrapper)
  const element = input.element as HTMLInputElement
  element.value = text
  element.setSelectionRange(text.length, text.length)
  await input.trigger('input')
}

async function pause(ms = Math.max(SUGGESTION_DELAY_MS, VALIDATION_DELAY_MS)): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
  await flushPromises()
}

const press = (wrapper: VueWrapper, key: string) => inputOf(wrapper).trigger('keydown', { key })
const options = (wrapper: VueWrapper) => wrapper.findAll('[role="option"]')

beforeEach(() => {
  vi.useFakeTimers()
  queryFieldsMock.mockReset()
  queryValuesMock.mockReset()
  queryValidateMock.mockReset()
  queryFieldsMock.mockImplementation(async (request?: { query?: { prefix?: string } }) => {
    const prefix = request?.query?.prefix
    return { data: prefix ? CATALOG.filter((entry) => entry.name.startsWith(prefix)) : CATALOG, error: undefined }
  })
  queryValuesMock.mockResolvedValue({
    data: { values: [{ value: 'cmd.exe', count: 12 }, { value: 'program files', count: 3 }] },
    error: undefined,
  })
  queryValidateMock.mockImplementation(async ({ body }: { body: { query: string } }) => {
    const start = body.query.indexOf('prcss')
    const errors =
      start < 0 ? [] : [{ start, end: start + 5, message: UNKNOWN_FIELD_MESSAGE, suggestion: 'process' }]
    return { data: { ok: errors.length === 0, errors }, error: undefined }
  })
})

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('the bar', () => {
  it('is a terminal input with a prompt and a labelled, combobox input', () => {
    const wrapper = mountBar()
    expect(wrapper.find('.terminal-input-group').exists()).toBe(true)
    const input = inputOf(wrapper)
    expect(input.attributes('role')).toBe('combobox')
    expect(input.attributes('aria-label')).toBe('Query')
    expect(input.attributes('aria-expanded')).toBe('false')
    expect(input.classes()).toContain('input-field')
  })

  it('starts with the applied query as its draft', () => {
    const wrapper = mountBar('lane:file')
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('lane:file')
  })

  it('keeps what is typed to itself until Enter', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'lane:file')
    expect(store.text).toBe('')
    await press(wrapper, 'Enter')
    await pause()
    expect(store.text).toBe('lane:file')
  })

  it('applies the draft trimmed', async () => {
    const wrapper = mountBar()
    await type(wrapper, '  lane:file  ')
    await press(wrapper, 'Enter')
    await pause()
    expect(store.text).toBe('lane:file')
  })

  it('applies an empty draft, which removes the query', async () => {
    const wrapper = mountBar('lane:file')
    await type(wrapper, '')
    await press(wrapper, 'Enter')
    await pause()
    expect(store.text).toBe('')
  })

  it('takes a query applied elsewhere, as back and forward do, into its draft', async () => {
    const wrapper = mountBar('one')
    store.setText('two')
    await flushPromises()
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('two')
  })

  it('shows the draft in a mirror behind the underline, hidden from assistive technology', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'lane:file')
    const mirror = wrapper.find('.query-bar__mirror')
    expect(mirror.attributes('aria-hidden')).toBe('true')
    expect(mirror.text()).toBe('lane:file')
  })
})

describe('clearing', () => {
  it('has no clear button while there is nothing to clear', () => {
    expect(mountBar().find('[aria-label="Clear query"]').exists()).toBe(false)
  })

  it('clears the draft and the applied query with the ✕', async () => {
    const wrapper = mountBar('lane:file')
    await wrapper.find('[aria-label="Clear query"]').trigger('click')
    await flushPromises()
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('')
    expect(store.text).toBe('')
  })

  it('offers the ✕ for a draft that is not applied yet too, and gives the focus back to the input', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'abc')
    await wrapper.find('[aria-label="Clear query"]').trigger('click')
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('')
    expect(document.activeElement).toBe(inputOf(wrapper).element)
  })
})

describe('the / key', () => {
  it('focuses the bar from anywhere on the page', () => {
    const wrapper = mountBar()
    const event = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true })
    document.body.dispatchEvent(event)
    expect(document.activeElement).toBe(inputOf(wrapper).element)
    expect(event.defaultPrevented).toBe(true)
  })

  it('leaves the key alone while an input, a textarea or an editable element has the focus', () => {
    const wrapper = mountBar()
    const other = document.createElement('input')
    document.body.append(other)
    other.focus()
    const event = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true })
    other.dispatchEvent(event)
    expect(document.activeElement).toBe(other)
    expect(event.defaultPrevented).toBe(false)
    expect(document.activeElement).not.toBe(inputOf(wrapper).element)
  })

  it('leaves / typed into the bar itself alone', async () => {
    const wrapper = mountBar()
    inputElement(wrapper).focus()
    const event = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true })
    inputOf(wrapper).element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
  })

  it('ignores / with a modifier, so browser shortcuts keep working', () => {
    const wrapper = mountBar()
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '/', ctrlKey: true, bubbles: true }))
    expect(document.activeElement).not.toBe(inputOf(wrapper).element)
  })

  it('stops listening once the bar is gone', () => {
    const wrapper = mountBar()
    wrapper.unmount()
    const event = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true })
    document.body.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
  })
})

describe('field suggestions', () => {
  it('lists the fields for what is typed, with their type, aliases and example', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'pro')
    await pause()
    expect(options(wrapper)).toHaveLength(2)
    const first = options(wrapper)[0]!.text()
    expect(first).toContain('process.name')
    expect(first).toContain('keyword')
    expect(first).toContain('proc, process')
    expect(first).toContain('cmd.exe')
    expect(inputOf(wrapper).attributes('aria-expanded')).toBe('true')
  })

  it('chooses with the arrow keys and Enter, inserting the name and a colon without applying the query', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'lane:file pro')
    await pause()
    await press(wrapper, 'ArrowDown')
    await press(wrapper, 'ArrowDown')
    expect(options(wrapper)[1]!.attributes('aria-selected')).toBe('true')
    await press(wrapper, 'ArrowUp')
    await press(wrapper, 'Enter')
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('lane:file process.name:')
    expect(store.text).toBe('')
  })

  it('completes the first suggestion with Tab when none is chosen', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'pro')
    await pause()
    await press(wrapper, 'Tab')
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('process.name:')
  })

  it('chooses with the mouse, without taking the focus from the input', async () => {
    const wrapper = mountBar()
    inputElement(wrapper).focus()
    await type(wrapper, 'pro')
    await pause()
    const mousedown = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    options(wrapper)[1]!.element.dispatchEvent(mousedown)
    await flushPromises()
    expect(mousedown.defaultPrevented).toBe(true)
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('process.pid:')
  })

  it('applies the query on Enter when no suggestion was chosen', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'pro')
    await pause()
    await press(wrapper, 'Enter')
    await pause()
    expect(store.text).toBe('pro')
  })

  it('closes the list with Esc and keeps the text', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'pro')
    await pause()
    await press(wrapper, 'Escape')
    expect(options(wrapper)).toHaveLength(0)
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('pro')
  })

  it('shows the list again on the arrow key after Esc', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'pro')
    await pause()
    await press(wrapper, 'Escape')
    await press(wrapper, 'ArrowDown')
    expect(options(wrapper)).toHaveLength(2)
  })

  it('gives the active option as the one the input names', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'pro')
    await pause()
    await press(wrapper, 'ArrowDown')
    const active = options(wrapper)[0]!
    expect(inputOf(wrapper).attributes('aria-activedescendant')).toBe(active.attributes('id'))
  })

  it('closes the list when the input loses the focus', async () => {
    const wrapper = mountBar()
    inputElement(wrapper).focus()
    await type(wrapper, 'pro')
    await pause()
    await inputOf(wrapper).trigger('blur')
    expect(options(wrapper)).toHaveLength(0)
  })
})

describe('value suggestions', () => {
  it('lists the values of the field after the colon, with their counts', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'process.name:')
    await pause()
    expect(options(wrapper).map((option) => option.text())).toEqual(['cmd.exe12', 'program files3'])
  })

  it('inserts a value, quoting one with a space, and closes the list', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'process.name:')
    await pause()
    await press(wrapper, 'ArrowUp')
    await press(wrapper, 'Enter')
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('process.name:"program files"')
    await pause()
    expect(options(wrapper)).toHaveLength(0)
  })

  it('offers no values for a field that is not a keyword', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'process.pid:')
    await pause()
    expect(options(wrapper)).toHaveLength(0)
    expect(queryValuesMock).not.toHaveBeenCalled()
  })
})

describe('validation', () => {
  it('underlines the span of an error, and says nothing for a good query', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'lane:file')
    await pause()
    expect(wrapper.findAll('.query-bar__error')).toHaveLength(0)
    expect(inputOf(wrapper).attributes('aria-invalid')).toBeUndefined()

    await type(wrapper, 'lane:file AND prcss:x')
    await pause()
    const underlined = wrapper.findAll('.query-bar__error')
    expect(underlined.map((span) => span.text())).toEqual(['prcss'])
    expect(inputOf(wrapper).attributes('aria-invalid')).toBe('true')
  })

  it('shows the first error under the bar, with its suggestion to apply', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'prcss:x')
    await pause()
    const message = wrapper.find('.query-bar__message')
    expect(message.text()).toContain(UNKNOWN_FIELD_MESSAGE)
    expect(message.find('button').text()).toContain('process')
  })

  it('replaces the wrong span with the suggestion when it is clicked', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'lane:file AND prcss:x')
    await pause()
    await wrapper.find('.query-bar__message button').trigger('click')
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe('lane:file AND process:x')
    await pause()
    expect(wrapper.find('.query-bar__message').exists()).toBe(false)
  })

  it('does not apply a draft with errors, and keeps the message', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'prcss:x')
    await pause()
    await press(wrapper, 'Enter')
    await pause()
    expect(store.text).toBe('')
    expect(wrapper.find('.query-bar__message').exists()).toBe(true)
  })

  it('checks a draft typed just before Enter instead of letting it through', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'prcss:x')
    await press(wrapper, 'Enter')
    await pause()
    expect(store.text).toBe('')
    expect(wrapper.findAll('.query-bar__error')).toHaveLength(1)
  })

  it('applies a draft when the validation request fails', async () => {
    queryValidateMock.mockResolvedValue({ data: undefined, error: { error: { message: 'down' } } })
    const wrapper = mountBar()
    await type(wrapper, 'prcss:x')
    await pause()
    expect(wrapper.find('.query-bar__message').exists()).toBe(false)
    await press(wrapper, 'Enter')
    await pause()
    expect(store.text).toBe('prcss:x')
  })

  it('shows the message of the underlined error in a tooltip on hover', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'lane:file AND prcss:x')
    await pause()
    const span = wrapper.find('.query-bar__error').element as HTMLElement
    span.getClientRects = () => [{ left: 100, right: 160, top: 10, bottom: 30 }] as unknown as DOMRectList
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)

    await inputOf(wrapper).trigger('mousemove', { clientX: 120, clientY: 20 })
    expect(wrapper.find('[role="tooltip"]').text()).toBe(UNKNOWN_FIELD_MESSAGE)

    await inputOf(wrapper).trigger('mousemove', { clientX: 400, clientY: 20 })
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
  })

  it('hides the tooltip when the pointer leaves the bar', async () => {
    const wrapper = mountBar()
    await type(wrapper, 'prcss:x')
    await pause()
    const span = wrapper.find('.query-bar__error').element as HTMLElement
    span.getClientRects = () => [{ left: 0, right: 60, top: 0, bottom: 30 }] as unknown as DOMRectList
    await inputOf(wrapper).trigger('mousemove', { clientX: 10, clientY: 10 })
    await inputOf(wrapper).trigger('mouseleave')
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
  })
})

describe('the cheat sheet', () => {
  it('opens from the ? button', async () => {
    const wrapper = mountBar()
    await wrapper.find('[aria-label="Query syntax help"]').trigger('click')
    await flushPromises()
    expect(document.body.querySelector('.query-cheat-sheet')).not.toBeNull()
  })

  it('fills the bar with a chosen example, without applying it', async () => {
    const wrapper = mountBar()
    await wrapper.find('[aria-label="Query syntax help"]').trigger('click')
    await flushPromises()
    document.body.querySelectorAll<HTMLButtonElement>('.query-cheat-sheet__example')[0]!.click()
    await flushPromises()
    expect((inputOf(wrapper).element as HTMLInputElement).value).toBe(QUERY_EXAMPLES[0]!.query)
    expect(store.text).toBe('')
  })
})
