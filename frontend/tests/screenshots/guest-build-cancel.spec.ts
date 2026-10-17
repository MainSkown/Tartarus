import type { Page } from '@playwright/test'
import { expect, screenshotPath, test } from './fixtures'
import { DESKTOP_PATH, expectNothingOverflows, mockDesktopSocketAt, openBuild, reachDesktop, snapshot } from './guest-build-harness'
import { CANCELLED, FAILED, JOB_READY, PAUSED, RUNNING_DESKTOP, SUCCEEDED, type BuildApiMock } from './guest-build-data'
import { gate } from './guest-page-data'

const CANCEL_BUTTON = '[data-build="cancel"]'
const REFUSAL = 'the build has already ended, so it cannot be cancelled'
const held = gate()

interface Scenario {
  name: string
  api: BuildApiMock
  width?: number
  desktop?: boolean
  act?: (page: Page) => Promise<void>
  expectVisible: (page: Page) => Promise<void>
}

const cancelAndConfirm = async (page: Page): Promise<void> => {
  await page.locator(CANCEL_BUTTON).click()
  await page.locator('.q-dialog').getByRole('button', { name: 'CANCEL BUILD' }).click()
}

const expectCancelInsidePage = async (page: Page): Promise<void> => {
  const button = await page.locator('.build-page__cancel-button').boundingBox()
  const container = await page.locator('.build-page').boundingBox()
  expect(button, 'the cancel button is rendered').not.toBeNull()
  expect(button!.x).toBeGreaterThanOrEqual(container!.x)
  expect(button!.x + button!.width).toBeLessThanOrEqual(container!.x + container!.width)
}

// The shared snapshot waits for every finite animation, and a toast's progress bar runs as long as its
// timeout, so that wait lets the toast time out before the picture is taken. Capture it at once instead.
const captureBeforeToastFades = async (page: Page, name: string): Promise<void> => {
  await expect(page.locator('.q-dialog')).toHaveCount(0)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

const showsCancel = async (page: Page): Promise<void> => {
  await expect(page.locator(CANCEL_BUTTON)).toHaveText('[CANCEL BUILD]')
  await expect(page.locator(CANCEL_BUTTON)).toBeEnabled()
  await expectCancelInsidePage(page)
}

const hidesCancel = async (page: Page): Promise<void> => {
  await expect(page.locator(CANCEL_BUTTON)).toHaveCount(0)
}

const SCENARIOS: Scenario[] = [
  { name: 'running', api: { reads: [RUNNING_DESKTOP] }, desktop: true, expectVisible: showsCancel },
  {
    name: 'confirm',
    api: { reads: [RUNNING_DESKTOP] },
    desktop: true,
    act: async (page) => page.locator(CANCEL_BUTTON).click(),
    expectVisible: async (page) => {
      await expect(page.locator('.q-dialog')).toContainText('Cancel this build?')
      await expect(page.locator('.q-dialog')).toContainText('The running step is stopped')
      await expect(page.locator('.q-dialog').getByRole('button', { name: 'CANCEL BUILD' })).toBeVisible()
    },
  },
  {
    name: 'cancelling',
    api: { reads: [RUNNING_DESKTOP], holdAction: held.opened },
    desktop: true,
    act: cancelAndConfirm,
    expectVisible: async (page) => {
      await expect(page.locator(CANCEL_BUTTON)).toHaveText('[CANCELLING...]')
      await expect(page.locator(CANCEL_BUTTON)).toBeDisabled()
      await expect.poll(() => page.locator(CANCEL_BUTTON).evaluate((button) => Number(getComputedStyle(button).opacity))).toBeLessThan(1)
    },
  },
  {
    name: 'cancelled',
    api: { reads: [RUNNING_DESKTOP], afterCancel: CANCELLED },
    desktop: true,
    act: cancelAndConfirm,
    expectVisible: async (page) => {
      await expect(page.locator('.build-notice--red')).toContainText('BUILD CANCELLED')
      await expect(page.locator('.build-notice--red')).toContainText('the build was cancelled')
      await expect(page.locator('.build-notice--red').getByRole('button', { name: '[RESUME]' })).toBeVisible()
      await expect(page.locator('.build-notice--red').getByRole('button', { name: '[RESTART]' })).toBeVisible()
      await hidesCancel(page)
    },
  },
  {
    name: 'refused',
    api: { reads: [RUNNING_DESKTOP], cancelRefusal: REFUSAL },
    desktop: true,
    act: cancelAndConfirm,
    expectVisible: async (page) => {
      const toast = page.locator('.q-notification.tt-toast--warning')
      await expect(toast).toContainText(REFUSAL)
      await expect(toast).not.toHaveClass(/-enter-active/)
    },
  },
  {
    name: 'paused',
    api: { reads: [PAUSED] },
    desktop: true,
    expectVisible: async (page) => {
      await showsCancel(page)
      await expect(page.locator('.build-notice--amber')).toContainText('Tamper Protection')
      await expect(page.locator('.build-notice--amber button', { hasText: '[CONTINUE]' })).toBeVisible()
    },
  },
  {
    name: 'absent-succeeded',
    api: { reads: [SUCCEEDED], job: JOB_READY },
    expectVisible: async (page) => {
      await expect(page.locator('[data-verdict="passed"]')).toBeVisible()
      await hidesCancel(page)
    },
  },
  {
    name: 'absent-failed',
    api: { reads: [FAILED] },
    expectVisible: async (page) => {
      await expect(page.locator('.build-notice--red')).toBeVisible()
      await hidesCancel(page)
    },
  },
  { name: 'running-narrow-600', width: 600, api: { reads: [RUNNING_DESKTOP] }, desktop: true, expectVisible: showsCancel },
  { name: 'running-narrow-390', width: 390, api: { reads: [RUNNING_DESKTOP] }, desktop: true, expectVisible: showsCancel },
]

for (const scenario of SCENARIOS) {
  const width = scenario.width ?? 1280
  test(`build-cancel-${scenario.name}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 900 : 1000 })
    const desktop = scenario.desktop ? await mockDesktopSocketAt(page, DESKTOP_PATH) : undefined
    await openBuild(page, scenario.api)
    if (desktop) await reachDesktop(desktop, 'connected', page)
    await scenario.act?.(page)
    await scenario.expectVisible(page)
    await expectNothingOverflows(page)
    if (scenario.name === 'refused') await captureBeforeToastFades(page, `build-cancel-${scenario.name}`)
    else await snapshot(page, `build-cancel-${scenario.name}`)
    if (scenario.name === 'cancelling') held.open()
  })
}
