import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FieldRead } from '@/api'
import { QUERY_EXAMPLES } from '@/services/query-examples'

const queryFieldsMock = vi.fn()
vi.mock('@/api', () => ({ queryFields: (...args: unknown[]) => queryFieldsMock(...args) }))

const { default: QueryCheatSheet } = await import('@/components/QueryCheatSheet.vue')

const CATALOG: FieldRead[] = [
  { name: 'process.name', type: 'keyword', aliases: ['proc', 'process'], description: '', example: '', lane: null, members: [], searchable: true },
  { name: 'destination.port', type: 'long', aliases: ['port'], description: '', example: '', lane: null, members: [], searchable: true },
]

async function openSheet(modelValue = true) {
  setActivePinia(createPinia())
  const wrapper = mount(QueryCheatSheet, {
    props: { modelValue },
    global: { plugins: [Quasar] },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

const dialog = () => document.body.querySelector('.query-cheat-sheet')

beforeEach(() => {
  queryFieldsMock.mockReset()
  queryFieldsMock.mockResolvedValue({ data: CATALOG, error: undefined })
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('QueryCheatSheet', () => {
  it('shows nothing while closed, and does not load the catalog', async () => {
    await openSheet(false)
    expect(dialog()).toBeNull()
    expect(queryFieldsMock).not.toHaveBeenCalled()
  })

  it('explains the grammar and lists the operators when open', async () => {
    await openSheet()
    const text = dialog()!.textContent!
    expect(text).toContain('QUERY SYNTAX')
    for (const operator of ['field:value', 'field:(a OR b)', 'field:*', 'AND', 'OR', 'NOT']) expect(text).toContain(operator)
  })

  it('builds the alias table from the catalog, not from a list of its own', async () => {
    await openSheet()
    const rows = [...dialog()!.querySelectorAll('.query-cheat-sheet__alias')].map((row) => [
      row.querySelector('.query-cheat-sheet__alias-name')!.textContent,
      row.querySelector('.query-cheat-sheet__alias-field')!.textContent,
    ])
    expect(rows).toEqual([
      ['port', 'destination.port'],
      ['proc', 'process.name'],
      ['process', 'process.name'],
    ])
  })

  it('lists the eight examples', async () => {
    await openSheet()
    const examples = [...dialog()!.querySelectorAll('.query-cheat-sheet__example')]
    expect(examples.map((example) => example.querySelector('code')!.textContent)).toEqual(QUERY_EXAMPLES.map((example) => example.query))
  })

  it('emits the example that is clicked and closes', async () => {
    const wrapper = await openSheet()
    const second = dialog()!.querySelectorAll<HTMLButtonElement>('.query-cheat-sheet__example')[1]!
    second.click()
    await flushPromises()
    expect(wrapper.emitted('choose')).toEqual([[QUERY_EXAMPLES[1]!.query]])
    expect(wrapper.emitted('update:modelValue')).toContainEqual([false])
  })

  it('closes from its close button', async () => {
    const wrapper = await openSheet()
    dialog()!.querySelector<HTMLButtonElement>('.query-cheat-sheet__close')!.click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toContainEqual([false])
  })

  it('still shows the grammar when the catalog could not be loaded', async () => {
    queryFieldsMock.mockResolvedValue({ data: undefined, error: { error: { message: 'down' } } })
    await openSheet()
    expect(dialog()!.textContent).toContain('field:value')
    expect(dialog()!.querySelectorAll('.query-cheat-sheet__alias')).toHaveLength(0)
  })
})
