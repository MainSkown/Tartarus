import type { Locator, Page } from '@playwright/test'
import {
  GUEST_READY_SYSTEM,
  expect,
  expectNoHorizontalOverflow,
  mockSettings,
  mockShell,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'
import { LAB1, LAB5_FAILED, LONG_NAME, gate } from './guest-page-data'
import { LONG_FAILED, LONG_REFUSAL, UNBUILT_FAILED, mockRetestApi, type RetestMockOptions } from './guest-retest-data'

const RETEST_BUTTON = '[RE-RUN SELF-TEST]'
const REFUSAL_409 = 'an analysis is running on lab5; the self-test reverts the snapshot, so it waits for the analysis to finish'

async function openGuestPage(page: Page, options: RetestMockOptions): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: { default_guest: null } })
  await mockRetestApi(page, options)
  await page.goto('/guest')
}

const card = (page: Page, name: string): Locator =>
  page.locator('.guest-card', { has: page.locator('.guest-card__name', { hasText: new RegExp(`^${name}$`) }) })

const retestButton = (page: Page, name: string): Locator => card(page, name).getByRole('button', { name: RETEST_BUTTON })

async function expectCardsFitTheirBoxes(page: Page): Promise<void> {
  await expectNoHorizontalOverflow(page)
  const overflowing = await page.locator('.guest-card').evaluateAll((cards) =>
    cards.filter((element) => element.scrollWidth > element.clientWidth).map((element) => element.querySelector('.guest-card__name')?.textContent),
  )
  expect(overflowing, 'cards whose content is wider than the card').toEqual([])
}

async function snapshot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  await waitForTransitions(page)
  await expectCardsFitTheirBoxes(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

test('guest-retest-failed-default-route-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [LAB5_FAILED] })
  await expect(retestButton(page, 'lab5')).toBeVisible()
  await snapshot(page, 'guest-retest-failed-default-route-guest')
})

test('guest-retest-failed-hover-route-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [LAB5_FAILED] })
  await retestButton(page, 'lab5').hover()
  await snapshot(page, 'guest-retest-failed-hover-route-guest')
})

test('guest-retest-failed-focus-route-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [LAB5_FAILED] })
  await retestButton(page, 'lab5').focus()
  await expect(retestButton(page, 'lab5')).toBeFocused()
  await snapshot(page, 'guest-retest-failed-focus-route-guest')
})

test('guest-retest-failed-busy-route-guest', async ({ page }) => {
  const held = gate()
  await openGuestPage(page, { guests: [LAB5_FAILED], holdRetest: held.opened })
  await retestButton(page, 'lab5').click()
  await expect(retestButton(page, 'lab5')).toBeDisabled()
  await snapshot(page, 'guest-retest-failed-busy-route-guest')
  held.open()
})

test('guest-retest-failed-refused-409-route-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [LAB5_FAILED], retestRefusal: REFUSAL_409 })
  await retestButton(page, 'lab5').click()
  await expect(card(page, 'lab5').locator('.guest-card__refusal')).toContainText('an analysis is running')
  await snapshot(page, 'guest-retest-failed-refused-409-route-guest')
})

test('guest-retest-failed-testing-after-click-route-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [LAB5_FAILED] })
  await retestButton(page, 'lab5').click()
  await expect(card(page, 'lab5').locator('.status-badge__label')).toHaveText('TESTING')
  await expect(retestButton(page, 'lab5')).toHaveCount(0)
  await snapshot(page, 'guest-retest-failed-testing-after-click-route-guest')
})

test('guest-retest-ready-no-button-route-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [LAB1] })
  await expect(card(page, 'lab1').locator('.guest-card__action', { hasText: 'CLONE' })).toBeVisible()
  await expect(retestButton(page, 'lab1')).toHaveCount(0)
  await snapshot(page, 'guest-retest-ready-no-button-route-guest')
})

test('guest-retest-failed-never-built-no-button-route-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [UNBUILT_FAILED] })
  await expect(card(page, 'lab6').locator('.guest-card__error')).toBeVisible()
  await expect(retestButton(page, 'lab6')).toHaveCount(0)
  await snapshot(page, 'guest-retest-failed-never-built-no-button-route-guest')
})

test('guest-retest-long-name-long-refusal-route-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [LONG_FAILED], retestRefusal: LONG_REFUSAL })
  await retestButton(page, LONG_NAME).click()
  await expect(card(page, LONG_NAME).locator('.guest-card__refusal')).toContainText('cannot run its self-test')
  await snapshot(page, 'guest-retest-long-name-long-refusal-route-guest')
})

test('guest-retest-narrow-900px-route-guest', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 })
  await openGuestPage(page, { guests: [LAB5_FAILED, LONG_FAILED], retestRefusal: REFUSAL_409 })
  await retestButton(page, 'lab5').click()
  await expect(card(page, 'lab5').locator('.guest-card__refusal')).toBeVisible()
  await snapshot(page, 'guest-retest-narrow-900px-route-guest')
})
