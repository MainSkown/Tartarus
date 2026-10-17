import type { Page } from '@playwright/test'
import type { SystemHealth } from '../../src/api'
import { mockDesktopSocketAt, type DesktopSocketMock } from './desktop-mock'
import { GUEST_READY_SYSTEM, expect, expectNoHorizontalOverflow, mockShell, screenshotPath, waitForTransitions } from './fixtures'
import { BUILD_ID, NOW, mockBuildApi, type BuildApiMock } from './guest-build-data'

export const DEGRADED_SYSTEM: SystemHealth = { ...GUEST_READY_SYSTEM, guest: { status: 'degraded', message: 'degraded: lab4 is building' } }
export const DESKTOP_PATH = '/ws/guests/lab4/desktop'

export type DesktopState = 'connected' | 'connecting' | 'timeout'

export { mockDesktopSocketAt }

export async function openBuild(page: Page, api: BuildApiMock): Promise<void> {
  // The step durations count from "now", so a fixed clock keeps them the same in every picture.
  await page.clock.setFixedTime(NOW)
  await mockShell(page, DEGRADED_SYSTEM)
  await mockBuildApi(page, api)
  await page.goto(`/guest/builds/${BUILD_ID}`)
}

export async function reachDesktop(desktop: DesktopSocketMock, state: DesktopState, page: Page): Promise<void> {
  await desktop.connected()
  if (state === 'connecting') return
  if (state === 'timeout') {
    desktop.close(4408, 'desktop not available yet: the guest has not started its display server')
    await expect(page.locator('[data-desktop="message"]')).toContainText('not available yet')
    return
  }
  desktop.admit()
  desktop.sendFrame()
  await expect(page.locator('[data-desktop="message"]')).toHaveCount(0)
  await expect
    .poll(() =>
      page.evaluate(() => {
        const canvas = document.querySelector<HTMLCanvasElement>('[data-desktop="screen"] canvas')
        if (!canvas || canvas.width === 0) return 0
        const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data
        let lit = 0
        for (let at = 0; at < pixels.length; at += 4) if (pixels[at]! + pixels[at + 1]! + pixels[at + 2]! > 60) lit += 1
        return lit
      }),
    )
    .toBeGreaterThan(50_000)
}

export async function snapshot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

export async function expectNothingOverflows(page: Page): Promise<void> {
  await expectNoHorizontalOverflow(page)
  const overflowing = await page
    .locator('.build-notice, .build-step, .build-header, .build-log__body, .build-step__text')
    .evaluateAll((elements) => elements.filter((element) => element.scrollWidth > element.clientWidth + 1).map((element) => element.className))
  expect(overflowing, 'elements whose content is wider than they are').toEqual([])
}

export const click = (label: string) => async (page: Page) => {
  await page.getByRole('button', { name: label }).click()
}
