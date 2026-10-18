import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify, Quasar, QSelect, type QBtn } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RULES, RULE_YAML, ruleDetailFixture } from './rules-fixtures'

vi.mock('@/api', () => ({
  rulesList: vi.fn(),
  rulesReload: vi.fn(),
  rulesRead: vi.fn(),
  rulesUpdate: vi.fn(),
}))

const { rulesList, rulesReload, rulesRead, rulesUpdate } = await import('@/api')
const RulesPage = (await import('@/pages/RulesPage.vue')).default

const succeeded = (data: unknown) => ({ data, error: undefined }) as never
const failed = (message: string) => ({ data: undefined, error: { error: { code: 'internal_error', message } } }) as never

async function mountPage() {
  setActivePinia(createPinia())
  const wrapper = mount(RulesPage, { global: { plugins: [Quasar] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

type Page = Awaited<ReturnType<typeof mountPage>>

const titles = (wrapper: Page) => wrapper.findAll('tbody [data-cell="title"]').map((cell) => cell.text())
const rowFor = (wrapper: Page, title: string) => wrapper.findAll('tbody tr').find((row) => row.text().includes(title))!
const [LEVEL, VALIDITY] = [0, 1]
const choose = async (wrapper: Page, which: number, value: string | null) => {
  wrapper.findAllComponents(QSelect)[which]!.vm.$emit('update:modelValue', value)
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  Notify.create = vi.fn()
  vi.mocked(rulesList).mockResolvedValue(succeeded(RULES))
  vi.mocked(rulesReload).mockResolvedValue(succeeded(RULES))
  vi.mocked(rulesRead).mockResolvedValue(succeeded(ruleDetailFixture({ id: 'b', title: 'Bravo rule' })))
})

describe('RulesPage list', () => {
  it('lists the rules, the most hit first and then the most severe', async () => {
    const wrapper = await mountPage()
    expect(titles(wrapper)).toEqual([
      'Bravo rule',
      'Charlie rule',
      'Delta rule',
      'Foxtrot correlation',
      'Echo broken',
      'Alpha rule',
    ])
  })

  it('notes where the rules are read from and where the analyst puts their own', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('.rules-note').text()).toContain('rules/sigma/custom/')
  })

  it('reads the whole note with its paths in place', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('.rules-note').text()).toBe(
      'Loaded from rules/sigma/: the shipped set in default/ and tartarus/. Put your own rules in rules/sigma/custom/; changed files reload by themselves, or press RELOAD.',
    )
  })

  it('says how many rules there are', async () => {
    expect((await mountPage()).find('.rules-count').text()).toBe('6 rules')
  })

  it('says so, and where to put one, when no rules are loaded', async () => {
    vi.mocked(rulesList).mockResolvedValue(succeeded([]))
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('> no rules loaded')
    expect(wrapper.text()).toContain('rules/sigma/custom/')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('shows the loader until the list arrives', async () => {
    vi.mocked(rulesList).mockReturnValue(new Promise(() => undefined) as never)
    const wrapper = await mountPage()
    expect(wrapper.find('.loader').exists()).toBe(true)
  })

  it('shows the failure with a retry that asks again', async () => {
    vi.mocked(rulesList).mockResolvedValueOnce(failed('database unreachable'))
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('> failed to load: database unreachable')
    expect(wrapper.find('table').exists()).toBe(false)

    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()
    expect(rulesList).toHaveBeenCalledTimes(2)
    expect(titles(wrapper)).toHaveLength(6)
  })
})

describe('RulesPage filters', () => {
  it('filters by the text of the title, path or id, ignoring case', async () => {
    const wrapper = await mountPage()
    await wrapper.find('.search-input input').setValue('ECHO')
    expect(titles(wrapper)).toEqual(['Echo broken'])
    expect(wrapper.find('.rules-count').text()).toBe('showing 1 of 6 rules')
  })

  it('filters by level', async () => {
    const wrapper = await mountPage()
    await choose(wrapper, LEVEL, 'critical')
    expect(titles(wrapper)).toEqual(['Bravo rule'])
  })

  it('filters by validity', async () => {
    const wrapper = await mountPage()
    await choose(wrapper, VALIDITY, 'invalid')
    expect(titles(wrapper)).toEqual(['Echo broken'])
  })

  it('offers every level and validity', async () => {
    const wrapper = await mountPage()
    const options = (which: number) => (wrapper.findAllComponents(QSelect)[which]!.props('options') as { label: string }[]).map((option) => option.label)
    expect(options(LEVEL)).toEqual(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'])
    expect(options(VALIDITY)).toEqual(['VALID', 'INVALID', 'UNSUPPORTED'])
  })

  it('says nothing matches when the filters leave no rule, and clears them on request', async () => {
    const wrapper = await mountPage()
    await wrapper.find('.search-input input').setValue('zzz')
    expect(wrapper.text()).toContain('> no rules match')
    expect(wrapper.find('table').exists()).toBe(false)

    await wrapper.find('.clear-filters-btn').trigger('click')
    await flushPromises()
    expect(titles(wrapper)).toHaveLength(6)
    expect((wrapper.find('.search-input input').element as HTMLInputElement).value).toBe('')
  })
})

describe('RulesPage selection', () => {
  it('opens the yaml of the rule whose row is clicked', async () => {
    const wrapper = await mountPage()
    await rowFor(wrapper, 'Bravo rule').trigger('click')
    await flushPromises()
    expect(rulesRead).toHaveBeenCalledWith(expect.objectContaining({ path: { rule_id: 'b' } }))
    expect(wrapper.find('.rule-detail__title').text()).toBe('Bravo rule')
    expect(wrapper.find('.rule-detail__yaml').text()).toBe(RULE_YAML.trimEnd())
    expect(rowFor(wrapper, 'Bravo rule').attributes('aria-current')).toBe('true')
  })

  it('opens it from the keyboard too', async () => {
    const wrapper = await mountPage()
    await rowFor(wrapper, 'Charlie rule').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(rulesRead).toHaveBeenCalledWith(expect.objectContaining({ path: { rule_id: 'c' } }))
  })

  it('shows the error of an invalid rule', async () => {
    vi.mocked(rulesRead).mockResolvedValue(succeeded(ruleDetailFixture({ ...RULES[4]!, yaml: 'title: [broken' })))
    const wrapper = await mountPage()
    await rowFor(wrapper, 'Echo broken').trigger('click')
    await flushPromises()
    expect(wrapper.find('.rule-detail__error').text()).toContain('unknown field: Foo')
  })

  it('closes the pane', async () => {
    const wrapper = await mountPage()
    await rowFor(wrapper, 'Bravo rule').trigger('click')
    await flushPromises()
    await wrapper.find('.rule-detail__close').trigger('click')
    expect(wrapper.find('.rule-detail').exists()).toBe(false)
    expect(wrapper.find('tbody [aria-current="true"]').exists()).toBe(false)
  })

  it('reads the file again when the retry of a failed read is pressed', async () => {
    vi.mocked(rulesRead).mockResolvedValueOnce(failed('The file is not available'))
    const wrapper = await mountPage()
    await rowFor(wrapper, 'Bravo rule').trigger('click')
    await flushPromises()
    expect(wrapper.find('.rule-detail').text()).toContain('failed to load: The file is not available')

    await wrapper.find('.rule-detail .retry-btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.rule-detail__yaml').exists()).toBe(true)
  })
})

describe('RulesPage enabled switch', () => {
  const switchOf = (wrapper: Page, title: string) => rowFor(wrapper, title).find('input[type="checkbox"]')

  it('saves the choice', async () => {
    vi.mocked(rulesUpdate).mockResolvedValue(succeeded({ ...RULES[1]!, enabled: false }))
    const wrapper = await mountPage()
    await switchOf(wrapper, 'Bravo rule').setValue(false)
    await flushPromises()
    expect(rulesUpdate).toHaveBeenCalledWith({ path: { rule_id: 'b' }, body: { enabled: false } })
    expect(rowFor(wrapper, 'Bravo rule').classes()).toContain('rule-row--disabled')
  })

  it('puts the switch back and toasts an error when the save fails', async () => {
    vi.mocked(rulesUpdate).mockResolvedValue(failed('rule not found'))
    const wrapper = await mountPage()
    await switchOf(wrapper, 'Bravo rule').setValue(false)
    await flushPromises()
    expect((switchOf(wrapper, 'Bravo rule').element as HTMLInputElement).checked).toBe(true)
    expect(Notify.create).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'tt-error', message: expect.stringContaining('Bravo rule') }),
    )
  })
})

describe('RulesPage reload', () => {
  const reloadButton = (wrapper: Page) => wrapper.find('.reload-btn')
  const reloading = (wrapper: Page) => wrapper.findComponent<typeof QBtn>('.reload-btn').props('loading')

  it('asks the server to read the directory again and says how many rules it holds', async () => {
    vi.mocked(rulesReload).mockResolvedValue(succeeded(RULES))
    const wrapper = await mountPage()
    await reloadButton(wrapper).trigger('click')
    await flushPromises()
    expect(rulesReload).toHaveBeenCalledOnce()
    expect(Notify.create).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'tt-success', message: 'Reloaded 6 rules: 1 invalid, 1 unsupported' }),
    )
  })

  it('shows the reload as running, keeps the list, and cannot be pressed twice', async () => {
    let finish: (value: never) => void = () => undefined
    vi.mocked(rulesReload).mockReturnValue(new Promise((resolve) => (finish = resolve)) as never)
    const wrapper = await mountPage()
    await reloadButton(wrapper).trigger('click')
    expect(reloading(wrapper)).toBe(true)
    expect(titles(wrapper)).toHaveLength(6)
    await reloadButton(wrapper).trigger('click')
    expect(rulesReload).toHaveBeenCalledTimes(1)

    finish(succeeded(RULES))
    await flushPromises()
    expect(reloading(wrapper)).toBe(false)
  })

  it('toasts an error and keeps the list when the reload fails', async () => {
    vi.mocked(rulesReload).mockResolvedValue(failed('rules directory unreadable'))
    const wrapper = await mountPage()
    await reloadButton(wrapper).trigger('click')
    await flushPromises()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-error' }))
    expect(Notify.create).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success' }))
    expect(titles(wrapper)).toHaveLength(6)
  })
})
