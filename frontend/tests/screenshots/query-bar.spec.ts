import type { Locator, Page } from '@playwright/test'
import {
  GUEST_READY_SYSTEM,
  expect,
  expectNoHorizontalOverflow,
  expectNoVerticalScroll,
  makeDetectedAnalysis,
  mockAnalyses,
  mockEvents,
  mockQuery,
  mockShell,
  screenshotPath,
  test,
  waitForTransitions,
  type EventsMock,
  type QueryMockOptions,
} from './fixtures'

const ID = 45
const EVENTS = `/analyses/${ID}/events`
const TWO_UNKNOWN_FIELDS = 'prcess.name:cmd.exe AND lnae:network'
const LONG_PATH = `C:\\Users\\Analyst\\AppData\\Local\\Temp\\${'nested_directory_'.repeat(8)}loader.exe`
const LONG_QUERY = [
  'process.name:cmd.exe',
  'api:(NtWriteVirtualMemory OR NtCreateThreadEx OR NtProtectVirtualMemory OR NtOpenProcess OR NtQueueApcThread)',
  'NOT file.path:*\\\\AppData\\\\Roaming\\\\*.exe',
  'destination.port >= 1024',
  'dns.question.name:*.onion',
  '"powershell -enc"',
].join(' AND ')

const FOUR_CHIPS =
  'f=process.name:cmd.exe&f=-api.name:NtDelayExecution&pid=9708&t=2026-10-13T15:39:34.250Z..2026-10-13T15:39:38.100Z'
const MANY_CHIPS = [
  ...['process.name:cmd.exe', '-process.name:conhost.exe', 'tartarus.lane:file', '-tartarus.lane:api', 'api.name:NtWriteFile'],
  ...['-api.name:NtDelayExecution', 'registry.hive:hklm', 'event.severity:3', `file.path:${LONG_PATH}`, '-dns.question.name:www.msftconnecttest.com'],
  ...['destination.port:443', 'rule.ruleset:sigma'],
]
  .map((chip) => `f=${encodeURIComponent(chip)}`)
  .concat(['pid=9708', 'pid=2476', 'pid=4412', 't=2026-10-13T15:39:34.250Z..'])
  .join('&')

let eventsMock: EventsMock

async function openEvents(page: Page, search = '', mock: QueryMockOptions = {}): Promise<Locator> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockQuery(page, mock)
  eventsMock = await mockEvents(page)
  await page.goto(`${EVENTS}${search ? `?${search}` : ''}`)
  const bar = page.getByRole('combobox', { name: 'Query' })
  await expect(bar).toBeVisible()
  await waitForTransitions(page)
  return bar
}

async function capture(page: Page, name: string): Promise<void> {
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`query-bar/${name}`) })
}

async function typeIntoBar(bar: Locator, text: string): Promise<void> {
  await bar.click()
  await bar.pressSequentially(text)
}

async function expectBarContainedInWindow(page: Page): Promise<void> {
  const { right } = await page.locator('.query-bar__group').evaluate((element) => {
    const box = element.getBoundingClientRect()
    return { right: box.right }
  })
  expect(right).toBeLessThanOrEqual(page.viewportSize()!.width)
}

test('query-bar-a-empty', async ({ page }) => {
  await openEvents(page)
  await expect(page.locator('.filter-chip')).toHaveCount(0)
  await expectNoVerticalScroll(page)
  await capture(page, '01-empty-no-chips')
})

test('query-bar-a2-empty-focused', async ({ page }) => {
  const bar = await openEvents(page)
  await page.keyboard.press('/')
  await expect(bar).toBeFocused()
  await capture(page, '01b-empty-focused-by-slash')
})

test('query-bar-b-field-suggestions', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, 'pro')
  await expect(page.getByRole('option').first()).toBeVisible()
  await bar.press('ArrowDown')
  await bar.press('ArrowDown')
  await expect(page.getByRole('option').nth(1)).toHaveAttribute('aria-selected', 'true')
  await capture(page, '02-field-suggestions-for-pro')
})

test('query-bar-b2-field-suggestions-after-term', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, 'lane:file AND NOT reg')
  await expect(page.getByRole('option').first()).toBeVisible()
  await capture(page, '02b-field-suggestions-after-another-term')
})

test('query-bar-c-value-suggestions', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, 'process.name:')
  await expect(page.getByRole('option').first()).toBeVisible()
  await capture(page, '03-value-suggestions-after-process-name')
})

test('query-bar-c2-value-suggestion-with-a-space-is-quoted', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, 'process.name:prog')
  await expect(page.getByRole('option')).toHaveCount(1)
  await bar.press('Tab')
  await expect(bar).toHaveValue('process.name:"program files updater.exe"')
  await capture(page, '03b-quoted-value-accepted')
})

test('query-bar-c3-no-suggestions-for-unknown-prefix', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, 'zzzz')
  await page.waitForTimeout(400)
  await expect(page.getByRole('option')).toHaveCount(0)
  await capture(page, '03c-no-suggestions-unknown-prefix')
})

test('query-bar-d-errors', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, TWO_UNKNOWN_FIELDS)
  await expect(page.locator('.query-bar__error')).toHaveCount(2)
  await expect(page.locator('.query-bar__message')).toContainText("unknown field 'prcess.name'")
  const box = (await page.locator('.query-bar__error').first().boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await expect(page.getByRole('tooltip')).toContainText("did you mean 'process.name'")
  await expectNoVerticalScroll(page)
  await capture(page, '04-two-errors-underline-tooltip-message')
})

test('query-bar-d2-second-error-tooltip', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, TWO_UNKNOWN_FIELDS)
  await expect(page.locator('.query-bar__error')).toHaveCount(2)
  const box = (await page.locator('.query-bar__error').nth(1).boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await expect(page.getByRole('tooltip')).toContainText("did you mean 'lane'")
  await capture(page, '04b-second-error-tooltip')
})

test('query-bar-d3-did-you-mean-applies', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, TWO_UNKNOWN_FIELDS)
  await page.locator('.query-bar__suggestion').click()
  await expect(bar).toHaveValue('process.name:cmd.exe AND lnae:network')
  await expect(page.locator('.query-bar__error')).toHaveCount(1)
  await capture(page, '04c-first-did-you-mean-applied')
})

test('query-bar-d4-error-not-applied-on-enter', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, TWO_UNKNOWN_FIELDS)
  await bar.press('Enter')
  await expect(page.locator('.query-bar__message')).toBeVisible()
  await expect(page).not.toHaveURL(/q=/)
})

test('query-bar-d5-validation-request-fails', async ({ page }) => {
  const bar = await openEvents(page, '', { validate: () => [] })
  await page.route((url) => url.pathname === '/api/query/validate', (route) => route.fulfill({ status: 500, json: { error: { code: 'internal_error', message: 'boom', details: {} } } }))
  await typeIntoBar(bar, TWO_UNKNOWN_FIELDS)
  await page.waitForTimeout(500)
  await expect(page.locator('.query-bar__error')).toHaveCount(0)
  await bar.press('Enter')
  await expect(page).toHaveURL(/q=prcess/)
  await capture(page, '04d-validation-failed-no-error-and-still-applies')
})

test('query-bar-e-chips', async ({ page }) => {
  await openEvents(page, `q=${encodeURIComponent('lane:file')}&${FOUR_CHIPS}`)
  await expect(page.locator('.filter-chip')).toHaveCount(4)
  await expect(page.locator('.filter-chip.is-negated')).toHaveCount(1)
  await expectNoVerticalScroll(page)
  await capture(page, '05-chips-normal-negated-pid-time')
})

test('query-bar-e2-chip-toggle-and-focus', async ({ page }) => {
  await openEvents(page, FOUR_CHIPS)
  const first = page.locator('.filter-chip').first()
  await first.focus()
  await capture(page, '05b-chip-keyboard-focus')
  await first.press('Enter')
  await expect(page.locator('.filter-chip.is-negated')).toHaveCount(2)
  await expect(page).toHaveURL(/f=-process\.name/)
  await capture(page, '05c-chip-toggled-to-negated')
  await page.getByRole('button', { name: 'Remove filter pid: 9708' }).click()
  await expect(page.locator('.filter-chip')).toHaveCount(3)
})

test('query-bar-f-many-chips-and-long-query', async ({ page }) => {
  const bar = await openEvents(page, `q=${encodeURIComponent(LONG_QUERY)}&${MANY_CHIPS}`)
  await expect(page.locator('.filter-chip')).toHaveCount(16)
  await bar.click()
  await bar.press('End')
  await expectNoHorizontalOverflow(page)
  await expectBarContainedInWindow(page)
  await capture(page, '06-many-chips-wrapping-long-query-scrolled-to-end')
  await bar.press('Home')
  await capture(page, '06b-long-query-scrolled-to-start')
})

test('query-bar-f2-long-query-underline-follows-scroll', async ({ page }) => {
  const bar = await openEvents(page)
  await typeIntoBar(bar, `${LONG_QUERY} AND prcess:x`)
  await expect(page.locator('.query-bar__error')).toHaveCount(1)
  await bar.press('End')
  await capture(page, '06c-long-query-error-underline-at-end')
  await bar.press('Home')
  await capture(page, '06d-long-query-error-scrolled-out-of-view')
})

test('query-bar-g-cheat-sheet', async ({ page }) => {
  await openEvents(page)
  await page.getByRole('button', { name: 'Query syntax help' }).click()
  await expect(page.getByText('QUERY SYNTAX')).toBeVisible()
  await expect(page.locator('.query-cheat-sheet__alias').first()).toBeVisible()
  await capture(page, '07-cheat-sheet')
  await page.locator('.query-cheat-sheet__example').nth(1).click()
  await expect(page.getByRole('combobox', { name: 'Query' })).toHaveValue(/NtWriteVirtualMemory/)
  await capture(page, '07b-example-filled-into-the-bar')
})

test('query-bar-g2-cheat-sheet-fits-without-scrolling-at-1280', async ({ page }) => {
  await openEvents(page)
  await page.getByRole('button', { name: 'Query syntax help' }).click()
  await expect(page.locator('.query-cheat-sheet__alias').first()).toBeVisible()
  await waitForTransitions(page)
  const { scrollHeight, clientHeight } = await page.locator('.query-cheat-sheet__body').evaluate((element) => ({
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
  }))
  expect(scrollHeight, 'the cheat sheet scrolls').toBeLessThanOrEqual(clientHeight)
})

test('query-bar-g3-cheat-sheet-narrow-window', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 720 })
  await openEvents(page)
  await page.getByRole('button', { name: 'Query syntax help' }).click()
  await expect(page.locator('.query-cheat-sheet__alias').first()).toBeVisible()
  await capture(page, '07c-cheat-sheet-narrow-800')
  await page.locator('.query-cheat-sheet__body').evaluate((element) => element.scrollTo(0, element.scrollHeight))
  await capture(page, '07d-cheat-sheet-narrow-800-scrolled-to-end')
})

test('query-bar-h-narrow-window', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 720 })
  await openEvents(page, `q=${encodeURIComponent('lane:file AND process.name:cmd.exe')}&${FOUR_CHIPS}`)
  await expect(page.locator('.filter-chip')).toHaveCount(4)
  await expectNoHorizontalOverflow(page)
  await capture(page, '08-narrow-800-with-chips')
})

test('query-bar-h2-narrow-window-many-chips-and-suggestions', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 720 })
  const bar = await openEvents(page, MANY_CHIPS)
  await expectNoHorizontalOverflow(page)
  await typeIntoBar(bar, 'dest')
  await expect(page.getByRole('option').first()).toBeVisible()
  await capture(page, '08b-narrow-800-many-chips-and-suggestions')
})

test('query-bar-i-slash-and-enter-write-the-url', async ({ page }) => {
  const bar = await openEvents(page)
  await page.keyboard.press('/')
  await bar.pressSequentially('process.name:cmd.exe')
  await bar.press('Escape')
  await bar.press('Enter')
  await expect(page).toHaveURL(/q=process\.name%3Acmd\.exe|q=process\.name:cmd\.exe/)
  await expect.poll(() => eventsMock.searches.at(-1)?.query).toBe('process.name:cmd.exe')
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  await capture(page, '09-applied-query-narrows-the-events-table')
})
