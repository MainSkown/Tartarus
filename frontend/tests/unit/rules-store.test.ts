import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ruleDetailFixture, ruleFixture, RULES } from './rules-fixtures'

const rulesListMock = vi.fn()
const rulesReloadMock = vi.fn()
const rulesReadMock = vi.fn()
const rulesUpdateMock = vi.fn()
vi.mock('@/api', () => ({
  rulesList: (...args: unknown[]) => rulesListMock(...args),
  rulesReload: (...args: unknown[]) => rulesReloadMock(...args),
  rulesRead: (...args: unknown[]) => rulesReadMock(...args),
  rulesUpdate: (...args: unknown[]) => rulesUpdateMock(...args),
}))

const { useRulesStore } = await import('@/stores/rules')
const { quietOn } = await import('@/services/quiet-statuses')

const succeeded = <T>(data: T) => ({ data, error: undefined })
const failed = (message = 'boom', status = 500) => ({
  data: undefined,
  error: { error: { code: 'internal_error', message, details: {} } },
  response: { status },
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

beforeEach(() => {
  setActivePinia(createPinia())
  rulesListMock.mockReset().mockResolvedValue(succeeded(RULES))
  rulesReloadMock.mockReset().mockResolvedValue(succeeded(RULES))
  rulesReadMock.mockReset().mockResolvedValue(succeeded(ruleDetailFixture()))
  rulesUpdateMock.mockReset()
})

describe('rules store: load', () => {
  it('lists the rules', async () => {
    const store = useRulesStore()
    await store.load()
    expect(store.items).toEqual(RULES)
    expect(store.loadError).toBeUndefined()
  })

  it('is loading until the list arrives', async () => {
    const pending = deferred<ReturnType<typeof succeeded>>()
    rulesListMock.mockReturnValue(pending.promise)
    const store = useRulesStore()
    const loading = store.load()
    expect(store.loading).toBe(true)
    pending.resolve(succeeded(RULES))
    await loading
    expect(store.loading).toBe(false)
  })

  it('keeps the failure message and no rules when the list fails', async () => {
    rulesListMock.mockResolvedValue(failed('database is down'))
    const store = useRulesStore()
    await store.load()
    expect(store.loadError).toBe('database is down')
    expect(store.items).toEqual([])
  })

  it('clears an earlier failure when a retry succeeds', async () => {
    rulesListMock.mockResolvedValueOnce(failed())
    const store = useRulesStore()
    await store.load()
    await store.load()
    expect(store.loadError).toBeUndefined()
    expect(store.items).toEqual(RULES)
  })
})

describe('rules store: reload', () => {
  it('replaces the rules with what the server read again and says it worked', async () => {
    const store = useRulesStore()
    await store.load()
    rulesReloadMock.mockResolvedValue(succeeded([ruleFixture({ id: 'new' })]))
    expect(await store.reload()).toBe(true)
    expect(store.items.map((rule) => rule.id)).toEqual(['new'])
  })

  it('is reloading while the request runs, without hiding the list', async () => {
    const store = useRulesStore()
    await store.load()
    const pending = deferred<ReturnType<typeof succeeded>>()
    rulesReloadMock.mockReturnValue(pending.promise)
    const reloading = store.reload()
    expect(store.reloading).toBe(true)
    expect(store.loading).toBe(false)
    expect(store.items).toEqual(RULES)
    pending.resolve(succeeded(RULES))
    await reloading
    expect(store.reloading).toBe(false)
  })

  it('keeps the old rules and reports failure when the reload fails', async () => {
    const store = useRulesStore()
    await store.load()
    rulesReloadMock.mockResolvedValue(failed())
    expect(await store.reload()).toBe(false)
    expect(store.items).toEqual(RULES)
    expect(store.reloading).toBe(false)
    expect(store.loadError).toBeUndefined()
  })

  it('drops the selection when the selected rule is gone, and reads the file again when it stays', async () => {
    const store = useRulesStore()
    await store.load()
    await store.select('b')
    rulesReadMock.mockClear()

    await store.reload()
    expect(store.selectedId).toBe('b')
    expect(rulesReadMock).toHaveBeenCalledTimes(1)

    rulesReloadMock.mockResolvedValue(succeeded([ruleFixture({ id: 'other' })]))
    await store.reload()
    expect(store.selectedId).toBeUndefined()
    expect(store.detail).toBeUndefined()
  })
})

describe('rules store: toggle', () => {
  it('flips the rule at once, before the server answers', async () => {
    const pending = deferred<ReturnType<typeof succeeded>>()
    rulesUpdateMock.mockReturnValue(pending.promise)
    const store = useRulesStore()
    await store.load()

    const toggling = store.toggleEnabled('a', false)
    expect(store.items.find((rule) => rule.id === 'a')!.enabled).toBe(false)
    expect(store.isToggling('a')).toBe(true)

    pending.resolve(succeeded(ruleFixture({ id: 'a', enabled: false, hits: 0 })))
    expect(await toggling).toBe(true)
    expect(store.isToggling('a')).toBe(false)
  })

  it('sends the choice for that rule', async () => {
    rulesUpdateMock.mockResolvedValue(succeeded(ruleFixture({ id: 'a', enabled: false })))
    const store = useRulesStore()
    await store.load()
    await store.toggleEnabled('a', false)
    expect(rulesUpdateMock).toHaveBeenCalledWith({ path: { rule_id: 'a' }, body: { enabled: false } })
  })

  it('takes the rule as the server returns it', async () => {
    rulesUpdateMock.mockResolvedValue(succeeded(ruleFixture({ id: 'a', enabled: false, hits: 99 })))
    const store = useRulesStore()
    await store.load()
    await store.toggleEnabled('a', false)
    expect(store.items.find((rule) => rule.id === 'a')).toMatchObject({ enabled: false, hits: 99 })
  })

  it('puts the switch back and says so when the server refuses', async () => {
    rulesUpdateMock.mockResolvedValue(failed('rule not found', 404))
    const store = useRulesStore()
    await store.load()
    expect(await store.toggleEnabled('a', false)).toBe(false)
    expect(store.items.find((rule) => rule.id === 'a')!.enabled).toBe(true)
    expect(store.isToggling('a')).toBe(false)
  })

  it('leaves the other rules alone when it rolls back', async () => {
    rulesUpdateMock.mockResolvedValue(failed())
    const store = useRulesStore()
    await store.load()
    await store.toggleEnabled('a', false)
    expect(store.items).toEqual(RULES)
  })

  it('ignores a second flip of a rule that is still being saved', async () => {
    rulesUpdateMock.mockReturnValue(new Promise(() => undefined))
    const store = useRulesStore()
    await store.load()
    void store.toggleEnabled('a', false)
    expect(await store.toggleEnabled('a', true)).toBe(false)
    expect(rulesUpdateMock).toHaveBeenCalledTimes(1)
  })

  it('does not enable a rule that cannot run', async () => {
    const store = useRulesStore()
    await store.load()
    expect(await store.toggleEnabled('e', true)).toBe(false)
    expect(rulesUpdateMock).not.toHaveBeenCalled()
  })

  it('does nothing for an unknown rule', async () => {
    const store = useRulesStore()
    await store.load()
    expect(await store.toggleEnabled('nope', true)).toBe(false)
    expect(rulesUpdateMock).not.toHaveBeenCalled()
  })
})

describe('rules store: selection', () => {
  it('reads the rule with its yaml', async () => {
    const store = useRulesStore()
    await store.load()
    await store.select('b')
    expect(rulesReadMock).toHaveBeenCalledWith({ path: { rule_id: 'b' }, meta: quietOn(404) })
    expect(store.selectedId).toBe('b')
    expect(store.detail?.yaml).toContain('title: Suspicious Remote Thread Creation')
    expect(store.detailLoading).toBe(false)
  })

  it('is loading the detail while the file is read, with the old one gone', async () => {
    const store = useRulesStore()
    await store.load()
    await store.select('b')
    const pending = deferred<ReturnType<typeof succeeded>>()
    rulesReadMock.mockReturnValue(pending.promise)
    const selecting = store.select('c')
    expect(store.detailLoading).toBe(true)
    expect(store.detail).toBeUndefined()
    pending.resolve(succeeded(ruleDetailFixture({ id: 'c' })))
    await selecting
    expect(store.detail?.id).toBe('c')
  })

  it('keeps the failure for the detail pane and no yaml', async () => {
    rulesReadMock.mockResolvedValue(failed('The file of rule b is not available', 404))
    const store = useRulesStore()
    await store.load()
    await store.select('b')
    expect(store.detailError).toBe('The file of rule b is not available')
    expect(store.detail).toBeUndefined()
    expect(store.selectedId).toBe('b')
  })

  it('shows only the latest of two quick selections', async () => {
    const slow = deferred<ReturnType<typeof succeeded>>()
    rulesReadMock.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(succeeded(ruleDetailFixture({ id: 'c' })))
    const store = useRulesStore()
    await store.load()
    const first = store.select('b')
    await store.select('c')
    slow.resolve(succeeded(ruleDetailFixture({ id: 'b' })))
    await first
    expect(store.detail?.id).toBe('c')
    expect(store.selectedId).toBe('c')
  })

  it('clears the selection', async () => {
    const store = useRulesStore()
    await store.load()
    await store.select('b')
    store.clearSelection()
    expect(store.selectedId).toBeUndefined()
    expect(store.detail).toBeUndefined()
    expect(store.detailError).toBeUndefined()
  })

  it('does not show a detail that arrives after the selection was cleared', async () => {
    const slow = deferred<ReturnType<typeof succeeded>>()
    rulesReadMock.mockReturnValue(slow.promise)
    const store = useRulesStore()
    await store.load()
    const selecting = store.select('b')
    store.clearSelection()
    slow.resolve(succeeded(ruleDetailFixture({ id: 'b' })))
    await selecting
    expect(store.detail).toBeUndefined()
  })

  it('exposes the selected rule from the list', async () => {
    const store = useRulesStore()
    await store.load()
    await store.select('e')
    expect(store.selected?.id).toBe('e')
  })
})
