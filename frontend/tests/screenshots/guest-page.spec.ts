import type { Locator, Page } from '@playwright/test'
import type { SystemHealth } from '../../src/api'
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
import {
  ADOPTED,
  BROKEN,
  LAB1,
  LAB2,
  LAB5_FAILED,
  LONG_GUEST,
  LONG_NAME,
  POPULATED,
  gate,
  mockGuestApi,
  type GuestApiMock,
} from './guest-page-data'

const DEGRADED_SYSTEM: SystemHealth = {
  ...GUEST_READY_SYSTEM,
  guest: { status: 'degraded', message: 'degraded: lab4 is building' },
}

async function openGuestPage(page: Page, api: GuestApiMock, health: SystemHealth = DEGRADED_SYSTEM): Promise<void> {
  await mockShell(page, health)
  await mockSettings(page, { getBody: { default_guest: null } })
  await mockGuestApi(page, api)
  await page.goto('/guest')
}

async function snapshot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

const card = (page: Page, name: string): Locator => page.locator('.guest-card', { has: page.locator('.guest-card__name', { hasText: new RegExp(`^${name}$`) }) })

async function expectNoCardOverflow(page: Page): Promise<void> {
  await expectNoHorizontalOverflow(page)
  const overflowing = await page.locator('.guest-card').evaluateAll((cards) =>
    cards.filter((element) => element.scrollWidth > element.clientWidth).map((element) => element.querySelector('.guest-card__name')?.textContent),
  )
  expect(overflowing, 'cards whose content is wider than the card').toEqual([])
}

test('guest-page-populated', async ({ page }) => {
  await openGuestPage(page, { guests: POPULATED })
  await expect(page.locator('.guest-card')).toHaveCount(POPULATED.length)
  await expect(card(page, 'lab4').getByText('46%')).toBeVisible()
  await expectNoCardOverflow(page)
  await snapshot(page, 'guest-page-populated')
})

for (const width of [700, 600]) {
  test(`guest-page-populated-narrow-${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openGuestPage(page, { guests: POPULATED })
    await expect(page.locator('.guest-card')).toHaveCount(POPULATED.length)
    await expectNoCardOverflow(page)
    await snapshot(page, `guest-page-populated-narrow-${width}`)
  })
}

test('guest-page-password-revealed', async ({ page }) => {
  await openGuestPage(page, { guests: POPULATED })
  await card(page, 'lab1').getByRole('button', { name: '[REVEAL]' }).click()
  await expect(card(page, 'lab1').locator('.guest-card__secret')).toHaveText('q7Zp-Lm2x-Rv9d')
  await expectNoCardOverflow(page)
  await snapshot(page, 'guest-page-password-revealed')
})

test('guest-page-checks-busy', async ({ page }) => {
  const held = gate()
  await openGuestPage(page, { guests: POPULATED, holdChecks: held.opened })
  await card(page, 'lab1').getByRole('button', { name: '[RUN CHECKS]' }).click()
  await expect(card(page, 'lab1').locator('.guest-checks')).toContainText('up to 2 minutes')
  await expectNoCardOverflow(page)
  await snapshot(page, 'guest-page-checks-busy')
  held.open()
})

test('guest-page-checks-result-one-failed', async ({ page }) => {
  await openGuestPage(page, { guests: POPULATED })
  await card(page, 'lab1').getByRole('button', { name: '[RUN CHECKS]' }).click()
  await expect(card(page, 'lab1').locator('.guest-checks__row')).toHaveCount(4)
  await expectNoCardOverflow(page)
  await snapshot(page, 'guest-page-checks-result-one-failed')
})

test('guest-page-checks-refused-409', async ({ page }) => {
  await openGuestPage(page, { guests: POPULATED, checkRefusal: 'An analysis is queued or running; the checks revert the snapshot, so they wait for it to finish' })
  await card(page, 'lab1').getByRole('button', { name: '[RUN CHECKS]' }).click()
  await expect(card(page, 'lab1').locator('.guest-checks__error')).toBeVisible()
  await expectNoCardOverflow(page)
  await snapshot(page, 'guest-page-checks-refused-409')
})

test('guest-page-delete-confirm', async ({ page }) => {
  await openGuestPage(page, { guests: POPULATED })
  await card(page, 'lab2').getByRole('button', { name: '[DELETE]' }).click()
  await expect(page.locator('.q-dialog')).toContainText('Delete lab2')
  await snapshot(page, 'guest-page-delete-confirm')
})

test('guest-page-delete-refused-409', async ({ page }) => {
  await openGuestPage(page, { guests: POPULATED, deleteRefusal: 'lab2 cannot be deleted while an analysis is queued or running' })
  await card(page, 'lab2').getByRole('button', { name: '[DELETE]' }).click()
  await page.locator('.q-dialog').getByRole('button', { name: 'DELETE' }).click()
  await expect(card(page, 'lab2').locator('.guest-card__refusal')).toBeVisible()
  await expectNoCardOverflow(page)
  await snapshot(page, 'guest-page-delete-refused-409')
})

test('guest-page-empty', async ({ page }) => {
  await openGuestPage(page, { guests: [] }, GUEST_READY_SYSTEM)
  await expect(page.getByText('> guest VM not built')).toBeVisible()
  await snapshot(page, 'guest-page-empty')
})

test('guest-page-control-service-unreachable', async ({ page }) => {
  await openGuestPage(page, { guests: [], listFailure: 'guest control list: unreachable (connection refused)' })
  await expect(page.getByText('> guest control service is not reachable')).toBeVisible()
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await snapshot(page, 'guest-page-control-service-unreachable')
})

test('guest-page-loading', async ({ page }) => {
  await openGuestPage(page, { guests: POPULATED, listDelayMs: 3000 })
  await expect(page.locator('.loader')).toBeVisible()
  await snapshot(page, 'guest-page-loading')
})

test('guest-page-adopted-giveaways-and-broken', async ({ page }) => {
  await openGuestPage(page, { guests: [ADOPTED, LAB1, BROKEN, LAB5_FAILED] })
  await expect(card(page, 'win').locator('.guest-card__giveaways')).toBeVisible()
  await expectNoCardOverflow(page)
  await snapshot(page, 'guest-page-adopted-giveaways-and-broken')
})

for (const width of [1280, 700]) {
  test(`guest-page-long-names-and-many-badges-${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openGuestPage(page, { guests: [LONG_GUEST, LAB2] })
    await card(page, LONG_NAME).getByRole('button', { name: '[REVEAL]' }).click()
    await expectNoCardOverflow(page)
    await snapshot(page, `guest-page-long-names-and-many-badges-${width}`)
  })
}

test('guest-page-header-popover', async ({ page }) => {
  await openGuestPage(page, { guests: POPULATED })
  await page.locator('.guest-health-trigger').click()
  await expect(page.locator('.guest-health-menu')).toContainText('lab5')
  await snapshot(page, 'guest-page-header-popover')
})

test('guest-page-header-popover-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 700 })
  await openGuestPage(page, { guests: [LONG_GUEST, ...POPULATED] })
  await page.locator('.guest-health-trigger').click()
  await expect(page.locator('.guest-health-menu')).toContainText(LONG_NAME)
  await snapshot(page, 'guest-page-header-popover-narrow-600')
})

test('guest-page-ready-state-only-one-guest', async ({ page }) => {
  await openGuestPage(page, { guests: [LAB2] }, GUEST_READY_SYSTEM)
  await expect(page.locator('.guest-card')).toHaveCount(1)
  await expect(card(page, 'lab2').getByText('DEFAULT')).toBeVisible()
  await snapshot(page, 'guest-page-ready-state-only-one-guest')
})
