import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  expect,
  expectNoHorizontalOverflow,
  mockAnalyses,
  mockSettings,
  mockShell,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'
import { mockGuests } from './guest-data'
import {
  FINISHED_BACKDROP,
  GUESTS,
  LONG_NAME_QUEUED,
  LONG_NAME_RUNNING,
  MANY_QUEUED,
  ONE_RUNNING,
  SETTINGS,
  THREE_RUNNING,
  TWO_QUEUED,
  queueOf,
} from './live-chip-parallel-data'

async function openDashboard(page: Page, running: AnalysisRead[], queued: AnalysisRead[], width = 1280): Promise<void> {
  await page.setViewportSize({ width, height: 800 })
  await mockShell(page, GUEST_READY_SYSTEM, queueOf(running, queued))
  await mockAnalyses(page, { items: [...running, ...queued, ...FINISHED_BACKDROP] })
  await page.goto('/')
  await expect(page.locator('.analysis-row')).toHaveCount(running.length + queued.length + FINISHED_BACKDROP.length)
}

async function openChipMenu(page: Page): Promise<void> {
  await page.locator('.live-chip').click()
  await expect(page.locator('.live-chip-menu')).toBeVisible()
}

async function openSubmitPicker(page: Page, running: AnalysisRead[], queued: AnalysisRead[]): Promise<void> {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockShell(page, GUEST_READY_SYSTEM, queueOf(running, queued))
  await mockSettings(page, { getBody: SETTINGS })
  await mockAnalyses(page, { items: [...running, ...queued] })
  await mockGuests(page, { guests: GUESTS })
  await page.goto('/')
  await page.getByRole('button', { name: '+ SUBMIT', exact: true }).click()
  await expect(page.locator('.submit-dialog')).toBeVisible()
  await page.locator('.q-field', { hasText: 'GUEST' }).click()
  await expect(page.locator('.guest-option-row').first()).toBeVisible()
}

test('live-chip-none-running', async ({ page }) => {
  await openDashboard(page, [], [])
  await expect(page.locator('.live-chip')).toHaveCount(0)
  await expect(page.locator('.header-queue')).toHaveText('QUEUE 0')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('live-chip-none-running') })
})

test('live-chip-one-running', async ({ page }) => {
  await openDashboard(page, ONE_RUNNING, [])
  await expect(page.locator('.live-chip')).toHaveText(/LIVE #42 \d\d:\d\d/)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('live-chip-one-running') })
})

test('live-chip-three-running', async ({ page }) => {
  await openDashboard(page, THREE_RUNNING, TWO_QUEUED)
  await expect(page.locator('.live-chip')).toHaveText('LIVE 3')
  await expect(page.locator('.header-queue')).toHaveText('QUEUE 2')
  await expect(page.locator('.queue-position').first()).toHaveText('1 for lab1')
  await openChipMenu(page)
  await expect(page.locator('.live-chip-menu__item')).toHaveCount(3)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('live-chip-three-running') })
})

test('live-chip-long-file-names', async ({ page }) => {
  await openDashboard(page, LONG_NAME_RUNNING, LONG_NAME_QUEUED)
  await openChipMenu(page)
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('live-chip-long-file-names') })
})

test('live-chip-many-queued', async ({ page }) => {
  await openDashboard(page, ONE_RUNNING, MANY_QUEUED)
  await expect(page.locator('.header-queue')).toHaveText('QUEUE 11')
  await expect(page.locator('.queue-position')).toHaveCount(MANY_QUEUED.length)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('live-chip-many-queued') })
})

test('live-chip-narrow-600', async ({ page }) => {
  await openDashboard(page, THREE_RUNNING, TWO_QUEUED, 600)
  await expect(page.locator('.live-chip')).toHaveText('LIVE 3')
  await openChipMenu(page)
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('live-chip-narrow-600') })
})

test('live-chip-picker-busy', async ({ page }) => {
  await openSubmitPicker(page, THREE_RUNNING, TWO_QUEUED)
  await expect(page.locator('.guest-option-row__busy').first()).toHaveText('busy')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('live-chip-picker-busy') })
})
