import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { COLUMNS_STORAGE_KEY, useEventColumns } from '@/composables/use-event-columns'

afterEach(() => window.localStorage.clear())

describe('useEventColumns', () => {
  it('starts with no extra columns', () => {
    expect(useEventColumns().chosen.value).toEqual([])
  })

  it('adds and removes a column, in the order chosen', () => {
    const columns = useEventColumns()
    columns.toggle('file.path')
    columns.toggle('api.name')
    expect(columns.chosen.value).toEqual(['file.path', 'api.name'])
    expect(columns.isChosen('api.name')).toBe(true)
    columns.toggle('file.path')
    expect(columns.chosen.value).toEqual(['api.name'])
    expect(columns.isChosen('file.path')).toBe(false)
  })

  it('remembers the choice for the next visit', async () => {
    useEventColumns().toggle('file.path')
    await nextTick()
    expect(useEventColumns().chosen.value).toEqual(['file.path'])
  })

  it('drops a remembered name the table no longer offers and anything that is not a list of names', () => {
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(['file.path', 'gone.field', 7]))
    expect(useEventColumns().chosen.value).toEqual(['file.path'])
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, '"nonsense"')
    expect(useEventColumns().chosen.value).toEqual([])
  })

  it('clears the choice', () => {
    const columns = useEventColumns()
    columns.toggle('file.path')
    columns.clear()
    expect(columns.chosen.value).toEqual([])
  })
})
