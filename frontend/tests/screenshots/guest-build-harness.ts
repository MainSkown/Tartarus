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
    .locator('.build-notice, .build-step, .build-header, .build-header__message, .build-header__description, .build-log__body, .build-log__progress, .build-step__text, .pane-heading')
    .evaluateAll((elements) => elements.filter((element) => element.scrollWidth > element.clientWidth + 1).map((element) => element.className))
  expect(overflowing, 'elements whose content is wider than they are').toEqual([])
}

const WIDE_LAYOUT_MIN_WIDTH = 901
const ALIGNMENT_TOLERANCE_PX = 1.5

interface HeaderBox {
  title: string
  top: number
  height: number
  titleMiddle: number
  buttonMiddles: number[]
  buttonBottoms: number[]
}

/** The panel headers share one height, their buttons sit on the title's line, and side by side STEPS and DESKTOP start level. */
export async function expectPanelHeadersAligned(page: Page, width: number): Promise<void> {
  const headers = await page.locator('.pane-heading').evaluateAll((elements): HeaderBox[] =>
    elements.map((element) => {
      const title = element.querySelector('.pane-heading__title')!.getBoundingClientRect()
      const box = element.getBoundingClientRect()
      const buttons = Array.from(element.querySelectorAll('.pane-heading__actions button')).map((button) => button.getBoundingClientRect())
      return {
        title: element.querySelector('.pane-heading__title')!.textContent?.trim() ?? '',
        top: box.top + window.scrollY,
        height: box.height,
        titleMiddle: title.top + title.height / 2,
        buttonMiddles: buttons.map((button) => button.top + button.height / 2),
        buttonBottoms: buttons.map((button) => button.bottom),
      }
    }),
  )
  if (headers.length === 0) return
  const tolerance = ALIGNMENT_TOLERANCE_PX
  for (const header of headers) {
    expect(Math.abs(header.height - headers[0]!.height), `${header.title} header height ${header.height} against ${headers[0]!.height}`).toBeLessThanOrEqual(tolerance)
  }
  const wrapped = (header: HeaderBox) => header.buttonMiddles.some((middle) => Math.abs(middle - header.titleMiddle) > tolerance)
  const sideBySide = width >= WIDE_LAYOUT_MIN_WIDTH
  for (const header of headers) {
    if (sideBySide) expect(wrapped(header), `${header.title}: the buttons are not on the title's line`).toBe(false)
  }
  const steps = headers.find((header) => header.title === 'STEPS')
  const desktop = headers.find((header) => header.title === 'DESKTOP')
  if (sideBySide && steps && desktop) expect(Math.abs(steps.top - desktop.top), 'STEPS and DESKTOP start at different heights').toBeLessThanOrEqual(tolerance)
}

export const click = (label: string) => async (page: Page) => {
  await page.getByRole('button', { name: label }).click()
}
