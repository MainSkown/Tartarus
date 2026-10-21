import type { Locator, Page } from '@playwright/test'
import type { AnalysisHitRead, ErrorEnvelope, Ioc, IocType } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeDetectedAnalysis,
  mockAnalyses,
  mockEvents,
  mockQuery,
  mockShell,
  mockViews,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'

const ID = 45
const LONG_URL = `http://${'subdomain.'.repeat(8)}evil.example/gate.php?id=${'0123456789abcdef'.repeat(12)}`
const MUTEX = 'Local\\SM0:2476:304:WilStaging_02'
const CHIP = '.ioc-analyses__chip'
const FAILED = '.ioc-analyses__failed'
const FAILED_TITLE = 'The analyses holding this indicator could not be loaded'

type Answer = { status: 200; hits: AnalysisHitRead[] } | { status: number; body: ErrorEnvelope }
/** Keyed `kind value`; an indicator without an answer here is an unmocked request and fails the test. */
type Answers = Record<string, Answer>

function hitsOf(count: number): AnalysisHitRead[] {
  return Array.from({ length: count }, (_, index) => ({ analysis_id: ID - 1 - index, count: 3 + index * 7 }))
}

const ONE: Answer = { status: 200, hits: [{ analysis_id: 44, count: 12 }] }
const MANY: Answer = { status: 200, hits: hitsOf(14) }
const NOT_PIVOTABLE: Answer = { status: 422, body: errorEnvelope('unprocessable', 'a mutex cannot be pivoted') }
const FAILURE: Answer = { status: 500, body: errorEnvelope('internal_error', 'OpenSearch is not answering') }

const IOC_ANALYSES_URL = (url: URL): boolean => /^\/api\/iocs\/[^/]+\/.+\/analyses$/.test(url.pathname)

async function mockIocAnalyses(page: Page, answers: Answers): Promise<void> {
  await page.route(IOC_ANALYSES_URL, async (route) => {
    const [, , , kind, ...rest] = new URL(route.request().url()).pathname.split('/')
    const value = decodeURIComponent(rest.slice(0, -1).join('/'))
    const answer = answers[`${kind} ${value}`]
    if (!answer) return route.fallback()
    if (answer.status === 200) return route.fulfill({ json: answer.hits })
    return route.fulfill({ status: answer.status, json: answer.body })
  })
}

function ioc(type: IocType, value: string, count: number): Ioc {
  return { type, value, count, context: `seen ${count} time(s) in this analysis`, source_event_ids: [], process: null, first_seen: null }
}

const IOCS: Ioc[] = [
  ioc('domain', 'tartarus-selftest.example', 2),
  ioc('domain', 'time.windows.com', 1),
  ioc('ip', '203.0.113.77', 214),
  ioc('url', LONG_URL, 1),
  ioc('mutex', MUTEX, 1),
]

const VIEW_ANSWERS: Answers = {
  'domain tartarus-selftest.example': MANY,
  'domain time.windows.com': ONE,
  'ip 203.0.113.77': FAILURE,
  [`url ${LONG_URL}`]: ONE,
  [`mutex ${MUTEX}`]: NOT_PIVOTABLE,
}

/** A failed lookup raises the app's persistent error toast; it is dismissed so the chip under it stays visible. */
async function dismissErrorToast(page: Page, answers: Answers): Promise<void> {
  if (!Object.values(answers).some((answer) => answer.status === 500)) return
  const toast = page.locator('.tt-toast--error')
  await expect(toast).toHaveCount(1)
  await toast.locator('.q-btn').click()
  await expect(toast).toHaveCount(0)
}

async function openIocs(page: Page, answers: Answers): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockViews(page, { iocs: { body: { iocs: IOCS, truncated_types: [] } } })
  await mockIocAnalyses(page, answers)
  await page.goto(`/analyses/${ID}/artifacts`)
  await page.locator('.artifact-sub-tabs').getByRole('tab', { name: /^IOCs/ }).click()
  await expect(page.locator('.artifact-panel:visible .loader')).toHaveCount(0)
  await expect(page.locator(`${CHIP}, ${FAILED}`).first()).toBeAttached()
  await dismissErrorToast(page, answers)
  await waitForTransitions(page)
}

async function settledIocs(page: Page): Promise<void> {
  await expect(page.locator(`${CHIP}, ${FAILED}`)).toHaveCount(4)
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
}

async function shoot(page: Page, name: string): Promise<void> {
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: screenshotPath(`ioc-analyses-link-${name}`), fullPage: true })
}

const rowOf = (page: Page, value: string) => page.locator('tr', { hasText: value })

test.describe('IOC view (artifacts)', () => {
  test('view-chips-count-one-many-error-and-422', async ({ page }) => {
    await openIocs(page, VIEW_ANSWERS)
    await settledIocs(page)
    await expect(rowOf(page, 'time.windows.com').locator(CHIP)).toHaveText(/Seen in 1 analysis$/)
    await expect(rowOf(page, 'tartarus-selftest.example').locator(CHIP)).toHaveText(/Seen in 14 analyses$/)
    await expect(rowOf(page, MUTEX).locator(`${CHIP}, ${FAILED}`)).toHaveCount(0)
    await shoot(page, 'view-chips')
  })

  test('view-menu-open', async ({ page }) => {
    await openIocs(page, VIEW_ANSWERS)
    await settledIocs(page)
    await rowOf(page, 'tartarus-selftest.example').locator(CHIP).click()
    await expect(page.locator('.ioc-analyses__menu')).toBeVisible()
    await expect(page.locator('.ioc-analyses__menu .q-item')).toHaveCount(14)
    await waitForTransitions(page)
    await shoot(page, 'view-menu-open')
  })

  test('view-error-icon-tooltip', async ({ page }) => {
    await openIocs(page, VIEW_ANSWERS)
    await settledIocs(page)
    const failed = rowOf(page, '203.0.113.77').locator(FAILED)
    await expect(failed).toHaveAttribute('title', FAILED_TITLE)
    await failed.hover()
    await waitForTransitions(page)
    await shoot(page, 'view-error-tooltip')
  })

  for (const width of NARROW_AND_WIDE_WIDTHS) {
    test(`view-width-${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await openIocs(page, VIEW_ANSWERS)
      await settledIocs(page)
      await shoot(page, `view-width-${width}`)
    })
  }
})

interface DrawerScenario {
  eventId: string
  answers: Answers
}

/** The destination address the sample DNS events resolve to: a second indicator the drawer also links. */
const RESOLVED_IP: Answer = ONE

async function openDrawer(page: Page, { eventId, answers }: DrawerScenario): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockQuery(page)
  await mockEvents(page)
  await mockIocAnalyses(page, { 'ip 192.168.150.1': RESOLVED_IP, ...answers })
  await page.goto(`/analyses/${ID}/events?e=${encodeURIComponent(eventId)}`)
  await expect(page.locator('.event-detail')).toBeVisible()
  await expect(page.locator(`.event-detail ${CHIP}, .event-detail ${FAILED}`).first()).toBeAttached()
  await dismissErrorToast(page, answers)
  await waitForTransitions(page)
}

/** The drawer is as tall as the window, so the row the link sits on is scrolled to before the capture. */
async function shootDrawer(page: Page, name: string, row: Locator): Promise<void> {
  await row.scrollIntoViewIfNeeded()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`ioc-analyses-link-${name}`) })
}

const fieldRow = (page: Page, name: string) => page.getByRole('row').filter({ has: page.getByRole('rowheader', { name, exact: true }) })

test.describe('event detail drawer', () => {
  test('drawer-chip-count-one', async ({ page }) => {
    await openDrawer(page, {
      eventId: '4180996f02fe03e9026f6412',
      answers: { 'domain www.msftconnecttest.com': ONE },
    })
    await expect(fieldRow(page, 'dns.question.name').locator(CHIP)).toHaveText(/Seen in 1 analysis$/)
    await shootDrawer(page, 'drawer-chip-one', fieldRow(page, 'dns.question.name'))
  })

  test('drawer-chip-many-menu-open', async ({ page }) => {
    await openDrawer(page, {
      eventId: '9f0ea17f7440bed6b04a486e',
      answers: { 'domain c2.evil-updates.net': MANY },
    })
    await fieldRow(page, 'dns.question.name').locator(CHIP).click()
    await expect(page.locator('.ioc-analyses__menu .q-item')).toHaveCount(14)
    await shootDrawer(page, 'drawer-chip-many-menu', fieldRow(page, 'dns.question.name'))
  })

  test('drawer-422-no-chip', async ({ page }) => {
    await openDrawer(page, {
      eventId: '9ca3717d44b58212cf14b797',
      answers: { 'domain tartarus-selftest.example': NOT_PIVOTABLE },
    })
    const row = fieldRow(page, 'dns.question.name')
    await expect(row).toContainText('tartarus-selftest.example')
    await expect(row.locator(CHIP)).toHaveCount(0)
    await expect(row.locator(FAILED)).toHaveCount(0)
    await shootDrawer(page, 'drawer-422', row)
  })

  test('drawer-error-muted-icon', async ({ page }) => {
    await openDrawer(page, {
      eventId: '3a8a2cb476d5ae8c0f50b619',
      answers: { 'domain time.windows.com': FAILURE },
    })
    await expect(fieldRow(page, 'dns.question.name').locator(FAILED)).toHaveAttribute('title', FAILED_TITLE)
    await shootDrawer(page, 'drawer-error', fieldRow(page, 'dns.question.name'))
  })
})
