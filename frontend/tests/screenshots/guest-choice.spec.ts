import type { Page } from '@playwright/test'
import type { AnalysisRead, SettingsBody } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeAnalysis,
  makeCleanAnalysis,
  makeDetectedAnalysis,
  mockAnalyses,
  mockSettings,
  mockShell,
  mockViews,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'
import {
  ALL_GUESTS,
  GUEST_BUILDING,
  GUEST_DEFENDER_OFF,
  GUEST_DEFENDER_ON,
  GUEST_FAILED,
  GUEST_LINUX,
  GUEST_LONG_NAME,
  mockGuests,
  type GuestsMockOptions,
} from './guest-data'

test.use({ timezoneId: 'UTC' })

const DIALOG_WIDTHS = [1280, 600]
const PAGE_WIDTHS = [1280, 700]

const SETTINGS: SettingsBody = {
  default_route: 'inetsim',
  default_timeout: 180,
  default_interactive: false,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}
const SAMPLE = { name: 'invoice_scan.exe', mimeType: 'application/octet-stream', buffer: Buffer.alloc(48 * 1024, 7) }

async function capture(page: Page, name: string, width: number): Promise<void> {
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`guest-choice-${name}-${width}`) })
}

async function openDialog(page: Page, width: number, guests: GuestsMockOptions = {}, settings: SettingsBody = SETTINGS): Promise<void> {
  await page.setViewportSize({ width, height: 800 })
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: settings })
  await mockAnalyses(page, { items: [] })
  await mockGuests(page, guests)
  await page.goto('/')
  await page.getByRole('button', { name: '+ SUBMIT', exact: true }).click()
  await expect(page.locator('.submit-dialog')).toBeVisible()
  await expect(page.getByLabel('TIMEOUT')).toHaveValue(String(settings.default_timeout))
}

async function chooseSample(page: Page): Promise<void> {
  await page.locator('input[type="file"]').setInputFiles(SAMPLE)
  await expect(page.locator('.file-hash')).toHaveText(/sha256 [0-9a-f]{64}/)
}

async function openSelect(page: Page, label: 'GUEST' | 'PACKAGE'): Promise<void> {
  await page.locator('.q-field', { hasText: label }).click()
  await expect(page.locator('.q-menu')).toBeVisible()
}

async function pickGuest(page: Page, name: string): Promise<void> {
  await openSelect(page, 'GUEST')
  await page.locator('.q-menu .q-item', { hasText: name }).click()
  await expect(page.locator('.guest-select .guest-chip__name')).toHaveText(name)
}

for (const width of DIALOG_WIDTHS) {
  test(`submit dialog, guest select closed, ${width}px`, async ({ page }) => {
    await openDialog(page, width)
    await chooseSample(page)
    await expect(page.locator('.guest-select .guest-chip__name')).toHaveText(GUEST_DEFENDER_ON.name)
    await expectNoHorizontalOverflow(page)
    await capture(page, 'dialog-default', width)
  })

  test(`submit dialog, guest select open, ${width}px`, async ({ page }) => {
    await openDialog(page, width)
    await openSelect(page, 'GUEST')
    await expect(page.locator('.q-menu .q-item[aria-disabled="true"]')).toHaveCount(2)
    await expect(page.locator('.q-menu .q-item[aria-disabled="true"]').first()).toContainText('building')
    await expectNoHorizontalOverflow(page)
    await capture(page, 'dialog-select-open', width)
  })

  test(`submit dialog, Defender-off guest with its packages, ${width}px`, async ({ page }) => {
    await openDialog(page, width)
    await chooseSample(page)
    await pickGuest(page, GUEST_DEFENDER_OFF.name)
    await openSelect(page, 'PACKAGE')
    await expect(page.locator('.q-menu .q-item')).toHaveCount(9)
    await expectNoHorizontalOverflow(page)
    await capture(page, 'dialog-defender-off-packages', width)
  })

  test(`submit dialog, a package the new guest lacks goes back to auto, ${width}px`, async ({ page }) => {
    await openDialog(page, width, { guests: [...ALL_GUESTS, GUEST_LINUX] })
    await chooseSample(page)
    await openSelect(page, 'PACKAGE')
    await page.locator('.q-menu .q-item', { hasText: 'ps1' }).click()
    await expect(page.locator('.q-field', { hasText: 'PACKAGE' })).toContainText('ps1')
    await pickGuest(page, GUEST_LINUX.name)
    await expect(page.locator('.q-field', { hasText: 'PACKAGE' })).toContainText('auto')
    await capture(page, 'dialog-package-reset', width)
  })

  test(`submit dialog, no guest ready, ${width}px`, async ({ page }) => {
    await openDialog(page, width, { guests: [GUEST_BUILDING, GUEST_FAILED] })
    await chooseSample(page)
    await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeDisabled()
    await expect(page.locator('.submit-reason')).toContainText('No guest is ready')
    await expect(page.locator('.guest-link')).toHaveAttribute('href', '/guest')
    await expectNoHorizontalOverflow(page)
    await capture(page, 'dialog-no-guest-ready', width)
  })

  test(`submit dialog, guest list could not be loaded, ${width}px`, async ({ page }) => {
    await openDialog(page, width, {
      listError: { status: 502, body: errorEnvelope('guest_control_unavailable', 'The guest control service does not answer') },
    })
    await chooseSample(page)
    await expect(page.locator('.guest-unavailable')).toBeVisible()
    await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeEnabled()
    await expectNoHorizontalOverflow(page)
    await capture(page, 'dialog-list-failed', width)
  })
}

test('submit dialog sends the chosen guest and package', async ({ page }) => {
  await openDialog(page, 1280)
  await chooseSample(page)
  await pickGuest(page, GUEST_DEFENDER_OFF.name)
  const request = page.waitForRequest((candidate) => candidate.method() === 'POST' && candidate.url().endsWith('/api/analyses'))
  await page.route(
    (url) => url.pathname === '/api/analyses',
    (route) => (route.request().method() === 'POST' ? route.fulfill({ status: 201, json: makeAnalysis({ id: 10 }) }) : route.fallback()),
  )
  await page.getByRole('button', { name: '▶ DETONATE' }).click()
  const body = (await request).postData() ?? ''
  expect(body).toContain(`"guest":"${GUEST_DEFENDER_OFF.name}"`)
})

async function openSettings(page: Page, width: number, settings: SettingsBody, guests: GuestsMockOptions = {}): Promise<void> {
  await page.setViewportSize({ width, height: 800 })
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: settings })
  await mockGuests(page, guests)
  await page.goto('/settings')
  await expect(page.locator('.save-btn')).toBeVisible()
}

for (const width of PAGE_WIDTHS) {
  test(`settings, default guest, ${width}px`, async ({ page }) => {
    await openSettings(page, width, { ...SETTINGS, default_guest: GUEST_DEFENDER_OFF.name })
    await expect(page.locator('.q-field', { hasText: 'DEFAULT GUEST' })).toContainText(GUEST_DEFENDER_OFF.name)
    await expectNoHorizontalOverflow(page)
    await capture(page, 'settings-default', width)
  })

  test(`settings, default guest select open, ${width}px`, async ({ page }) => {
    await openSettings(page, width, { ...SETTINGS, default_guest: null })
    await page.locator('.q-field', { hasText: 'DEFAULT GUEST' }).click()
    await expect(page.locator('.q-menu')).toBeVisible()
    await expect(page.locator('.q-menu .q-item')).toHaveCount(4)
    await capture(page, 'settings-select-open', width)
  })

  test(`settings, the stored guest no longer exists, ${width}px`, async ({ page }) => {
    await openSettings(page, width, { ...SETTINGS, default_guest: 'lab2-removed-last-week' })
    await expect(page.locator('.guest-note')).toHaveText('lab2-removed-last-week no longer exists: the first ready guest is used')
    await expectNoHorizontalOverflow(page)
    await capture(page, 'settings-stale-name', width)
  })
}

const GUEST_ANALYSES: AnalysisRead[] = [
  makeDetectedAnalysis({ id: 6, filename: 'invoice_scan.exe', guest: GUEST_DEFENDER_ON.name, guest_badges: GUEST_DEFENDER_ON.badges }),
  makeDetectedAnalysis({ id: 5, filename: 'loader.ps1', score: 4.2, max_severity: 'medium', guest: GUEST_DEFENDER_OFF.name, guest_badges: GUEST_DEFENDER_OFF.badges }),
  makeCleanAnalysis({ id: 4, filename: 'quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo.pdf.exe', guest: GUEST_LONG_NAME.name, guest_badges: GUEST_LONG_NAME.badges }),
  makeAnalysis({ id: 3, status: 'running', filename: 'payload.bin', started_at: '2026-10-12T09:14:30Z', guest: GUEST_DEFENDER_ON.name, guest_badges: GUEST_DEFENDER_ON.badges }),
  makeAnalysis({ id: 2, status: 'queued', filename: 'deleted_guest_sample.dll', guest: 'win10-removed', guest_badges: [] }),
  makeCleanAnalysis({ id: 1, filename: 'before_guests.exe' }),
]

for (const width of PAGE_WIDTHS) {
  test(`dashboard, rows of different guests, ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await mockShell(page, GUEST_READY_SYSTEM)
    await mockAnalyses(page, { items: GUEST_ANALYSES })
    await page.goto('/')
    await expect(page.locator('.analysis-row')).toHaveCount(GUEST_ANALYSES.length)
    await expect(page.locator('.analysis-row .guest-chip')).toHaveCount(5)
    await expectNoHorizontalOverflow(page)
    const { scrollWidth, clientWidth } = await page.locator('.tt-table-scroll').evaluate((element) => ({ scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }))
    expect(scrollWidth, `the table scrolls sideways at ${width}px`).toBeLessThanOrEqual(clientWidth)
    await capture(page, 'dashboard', width)
  })

  for (const [label, analysis] of [
    ['defender-on', makeDetectedAnalysis({ id: 7, guest: GUEST_DEFENDER_ON.name, guest_badges: GUEST_DEFENDER_ON.badges })],
    ['long-name', makeDetectedAnalysis({ id: 7, guest: GUEST_LONG_NAME.name, guest_badges: GUEST_LONG_NAME.badges })],
  ] as const) {
    test(`analysis header, guest chip (${label}), ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 })
      await mockShell(page, GUEST_READY_SYSTEM)
      await mockAnalyses(page, { items: [analysis] })
      await mockViews(page)
      await page.goto(`/analyses/${analysis.id}`)
      await expect(page.locator('.analysis-header__guest .guest-chip__name')).toHaveText(analysis.guest!)
      await expectNoHorizontalOverflow(page)
      await capture(page, `header-${label}`, width)
    })
  }
}
