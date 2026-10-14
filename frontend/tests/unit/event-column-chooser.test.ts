import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FieldRead } from '@/api'

const queryFieldsMock = vi.fn()
vi.mock('@/api', () => ({ queryFields: (...args: unknown[]) => queryFieldsMock(...args) }))

const { default: EventColumnChooser } = await import('@/components/EventColumnChooser.vue')

function field(name: string, overrides: Partial<FieldRead> = {}): FieldRead {
  return { name, type: 'keyword', aliases: [], description: `about ${name}`, example: '', lane: null, members: [], searchable: true, ...overrides }
}

const CATALOG = [field('file.path'), field('api.name'), field('destination.port', { type: 'long' }), field('process.command_line')]

async function openChooser(chosen: string[] = []) {
  setActivePinia(createPinia())
  const wrapper = mount(EventColumnChooser, { props: { chosen }, attachTo: document.body, global: { plugins: [Quasar] } })
  await wrapper.find('button').trigger('click')
  await flushPromises()
  return wrapper
}

const menu = () => document.body.querySelector('.column-chooser') as HTMLElement

beforeEach(() => {
  document.body.innerHTML = ''
  queryFieldsMock.mockReset()
  queryFieldsMock.mockResolvedValue({ data: CATALOG })
})

describe('EventColumnChooser', () => {
  it('lists the fields the table can show, grouped, and loads the catalog on opening', async () => {
    await openChooser()
    expect(queryFieldsMock).toHaveBeenCalledTimes(1)
    const groups = [...menu().querySelectorAll('.column-chooser__group')].map((group) => group.textContent)
    expect(groups).toEqual(['file', 'api', 'destination'])
    expect(menu().textContent).not.toContain('process.command_line')
  })

  it('shows which fields are chosen and says how many on the button', async () => {
    const wrapper = await openChooser(['api.name'])
    const boxes = [...menu().querySelectorAll<HTMLInputElement>('input[type="checkbox"]')]
    expect(boxes.map((box) => box.checked)).toEqual([false, true, false])
    expect(wrapper.find('.column-chooser__count').text()).toBe('+1')
  })

  it('asks to toggle a field', async () => {
    const wrapper = await openChooser()
    menu().querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[0]!.click()
    expect(wrapper.emitted('toggle')).toEqual([['file.path']])
  })

  it('narrows the list by what is typed', async () => {
    await openChooser()
    const input = menu().querySelector('input[type="text"], input:not([type])') as HTMLInputElement
    input.value = 'dest'
    input.dispatchEvent(new Event('input'))
    await flushPromises()
    expect([...menu().querySelectorAll('.column-chooser__name')].map((name) => name.textContent)).toEqual(['destination.port'])
  })

  it('resets the choice, and cannot when nothing is chosen', async () => {
    const empty = await openChooser()
    expect((menu().querySelector('.column-chooser__reset') as HTMLButtonElement).disabled).toBe(true)
    empty.unmount()
    document.body.innerHTML = ''
    const chosen = await openChooser(['api.name'])
    ;(menu().querySelector('.column-chooser__reset') as HTMLButtonElement).click()
    expect(chosen.emitted('clear')).toHaveLength(1)
  })
})
