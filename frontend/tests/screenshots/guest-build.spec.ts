import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { DESKTOP_PATH, click, expectNothingOverflows, mockDesktopSocketAt, openBuild, reachDesktop, snapshot, type DesktopState } from './guest-build-harness'
import {
  CLONE_RUNNING,
  FAILED,
  GUESTS_SELFTEST_FAILED,
  JOB_READY,
  JOB_SELFTEST_FAILED,
  LONG,
  PAUSED,
  RUNNING_DESKTOP,
  RUNNING_EARLY,
  SELFTEST_JOB,
  SUCCEEDED,
  type BuildApiMock,
} from './guest-build-data'
import { gate } from './guest-page-data'

const WIDTHS = [1280, 700, 600]

interface Scenario {
  name: string
  api: BuildApiMock
  desktop?: DesktopState
  act?: (page: Page) => Promise<void>
  expectVisible?: (page: Page) => Promise<void>
}

const held = gate()

const SCENARIOS: Scenario[] = [
  { name: 'running-early', api: { reads: [RUNNING_EARLY] }, expectVisible: (page) => expect(page.locator('.build-step--running')).toContainText('DEFINE') },
  { name: 'running-desktop-connected', api: { reads: [RUNNING_DESKTOP] }, desktop: 'connected' },
  { name: 'running-desktop-connecting', api: { reads: [RUNNING_DESKTOP] }, desktop: 'connecting', expectVisible: (page) => expect(page.locator('[data-desktop="message"]')).toContainText('connecting to the desktop') },
  { name: 'running-desktop-not-available-yet', api: { reads: [RUNNING_DESKTOP] }, desktop: 'timeout' },
  { name: 'paused-with-desktop', api: { reads: [PAUSED] }, desktop: 'connected', expectVisible: (page) => expect(page.locator('.build-notice--amber')).toContainText('Tamper Protection') },
  {
    name: 'paused-continue-busy',
    api: { reads: [PAUSED], holdAction: held.opened },
    desktop: 'connected',
    act: click('[CONTINUE]'),
    expectVisible: (page) => expect(page.locator('.build-notice--amber button')).toBeDisabled(),
  },
  { name: 'failed', api: { reads: [FAILED] }, expectVisible: (page) => expect(page.locator('.build-notice--red')).toContainText('provision exited with code 1') },
  {
    name: 'failed-restart-confirm',
    api: { reads: [FAILED] },
    act: click('[RESTART]'),
    expectVisible: (page) => expect(page.locator('.q-dialog')).toContainText('Restart the build of lab4'),
  },
  {
    name: 'failed-action-refused-409',
    api: { reads: [FAILED], actionRefusal: 'A sample is being analysed; the build waits until the analysis has finished' },
    act: click('[RESUME]'),
    expectVisible: (page) => expect(page.locator('.build-notice__error')).toBeVisible(),
  },
  { name: 'selftest-running', api: { reads: [SUCCEEDED], job: SELFTEST_JOB }, expectVisible: (page) => expect(page.locator('[data-build="message"]')).toHaveText('Self-test: analysis running') },
  { name: 'ready', api: { reads: [SUCCEEDED], job: JOB_READY }, expectVisible: (page) => expect(page.locator('[data-verdict="passed"]')).toBeVisible() },
  {
    name: 'selftest-failed',
    api: { reads: [SUCCEEDED], job: JOB_SELFTEST_FAILED, guests: GUESTS_SELFTEST_FAILED },
    expectVisible: (page) => expect(page.locator('[data-verdict="failed"]')).toContainText('unregistered'),
  },
  { name: 'not-found', api: { reads: [{ failure: 404, message: 'build build-lab4 does not exist' }] }, expectVisible: (page) => expect(page.getByText('> build not found')).toBeVisible() },
  {
    name: 'control-unreachable',
    api: { reads: [{ failure: 502, message: 'guest control: unreachable (connection refused)' }] },
    expectVisible: (page) => expect(page.getByText('> the guest control service is not reachable')).toBeVisible(),
  },
  { name: 'loading', api: { reads: [RUNNING_EARLY], readDelayMs: 4000 }, expectVisible: (page) => expect(page.locator('.loader')).toBeVisible() },
  { name: 'clone', api: { reads: [CLONE_RUNNING] }, desktop: 'connected', expectVisible: (page) => expect(page.locator('[data-build="kind"]')).toHaveText('CLONE') },
  { name: 'long-log-and-steps', api: { reads: [LONG] }, expectVisible: (page) => expect(page.locator('.build-step')).toHaveCount(17) },
]

for (const scenario of SCENARIOS) {
  for (const width of WIDTHS) {
    const name = `guest-build-${scenario.name}${width === 1280 ? '' : `-narrow-${width}`}`
    test(name, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 1280 ? 900 : 1000 })
      const desktop = scenario.desktop ? await mockDesktopSocketAt(page, DESKTOP_PATH) : undefined
      await openBuild(page, scenario.api)
      if (desktop && scenario.desktop) await reachDesktop(desktop, scenario.desktop, page)
      await scenario.act?.(page)
      await scenario.expectVisible?.(page)
      if (scenario.name !== 'loading') await expect(page.locator('.loader[role="status"]')).toHaveCount(scenario.name === 'running-desktop-connecting' ? 1 : 0)
      await expectNothingOverflows(page)
      await snapshot(page, name)
      if (scenario.name === 'paused-continue-busy') held.open()
    })
  }
}
