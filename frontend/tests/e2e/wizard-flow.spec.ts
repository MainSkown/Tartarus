import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

// The image the stack's data/iso holds; the wizard lists it by file name.
const POLISH_ISO = 'Win11_25H2_Polish_x64_v2.iso'
const GUEST = 'e2e-wizard'
const TAKEN_NAME = 'win'
const NAME_RULE = 'Use 2 to 32 lower-case letters, digits or hyphens, starting with a letter'
const TAKEN_MESSAGE = 'Another guest is already called win'
const GIVEAWAY_MESSAGE = "contains 'sandbox', which tells a sample what the machine is"
const GIVEAWAY_COMPUTER_NAME = 'sandbox-1'
const RANDOM_PLACEHOLDER = 'chosen at build time'
// The profile's rule for a computer name, as the backend states it; the generated value must match it.
const COMPUTER_NAME_RULE = /^(?!\d+$)[A-Za-z0-9]([A-Za-z0-9-]{0,13}[A-Za-z0-9])?$/
const IN_PROGRESS_STATES = ['building', 'testing']
const BUILD_URL = /\/guest\/builds\/[^/]+$/

const TEST_TIMEOUT_MS = 600_000
const BUILD_START_WAIT_MS = 180_000
const CANCEL_WAIT_MS = 120_000
const STACK_BACK_WAIT_MS = 240_000

interface GuestRecord {
  name: string
  state: string
  build_id: string | null
  identity: { account?: string; machine?: string }
}

const continueButton = (page: Page) => page.getByRole('button', { name: '[CONTINUE]' })
const guestCard = (page: Page): Locator => page.locator('.guest-card', { has: page.locator('.guest-card__name', { hasText: new RegExp(`^${GUEST}$`) }) })
const identityField = (page: Page, label: string): Locator => page.locator('.identity-field', { has: page.getByLabel(label, { exact: true }) })

async function readGuests(request: APIRequestContext): Promise<{ status: number; guests: GuestRecord[] }> {
  const response = await request.get('/api/guests')
  return { status: response.status(), guests: response.status() === 200 ? await response.json() : [] }
}

async function guestsOrFail(request: APIRequestContext): Promise<GuestRecord[]> {
  const { status, guests } = await readGuests(request)
  expect(status, 'GET /api/guests').toBe(200)
  return guests
}

async function wizardGuest(request: APIRequestContext): Promise<GuestRecord | undefined> {
  return (await guestsOrFail(request)).find((guest) => guest.name === GUEST)
}

const summaryOf = (guests: GuestRecord[]) => guests.map((guest) => `${guest.name}:${guest.state}`).sort()

// Only runs when the guest was absent at the start (the test fails otherwise), so whatever carries
// the name now is the one this run built. An in-progress build is cancelled first: the engine
// refuses to delete a guest that is being built, and a build left running blocks every analysis.
async function removeWizardGuest(request: APIRequestContext): Promise<void> {
  const guest = await wizardGuest(request)
  if (!guest) return
  if (IN_PROGRESS_STATES.includes(guest.state) && guest.build_id) {
    const cancelled = await request.post(`/api/guests/builds/${guest.build_id}/cancel`)
    expect(cancelled.status(), 'cancelling the wizard build during cleanup').toBe(202)
    await expect
      .poll(async () => (await wizardGuest(request))?.state ?? 'gone', { timeout: CANCEL_WAIT_MS })
      .not.toMatch(/^(building|testing)$/)
  }
  const deleted = await request.delete(`/api/guests/${GUEST}`)
  expect(deleted.status(), `DELETE /api/guests/${GUEST} during cleanup`).toBe(204)
}

test('the wizard builds a guest, a cancelled build ends failed and the guest is deleted', async ({ page, request }) => {
  test.setTimeout(TEST_TIMEOUT_MS)
  const originalGuests = summaryOf(await guestsOrFail(request))
  expect(await wizardGuest(request), `a guest named ${GUEST} already exists; this spec does not delete a guest it did not start. Remove it with DELETE /api/guests/${GUEST} and run again`).toBeUndefined()

  try {
    await test.step('(1) the Guests page leads to the wizard, which lists the real image', async () => {
      await page.goto('/guest')
      await page.getByRole('link', { name: '[+ NEW GUEST]' }).click()
      await expect(page).toHaveURL(/\/guest\/new$/)
      const row = page.getByRole('radio', { name: new RegExp(POLISH_ISO) })
      await expect(row).toBeVisible()
      await expect(row).toContainText(/\d+ editions?/)
      await expect(row).toContainText(/10\.0\.\d+/)
      await expect(row).toContainText('pl-PL')
      await row.click()
      await continueButton(page).click()
    })

    await test.step('(2) the settings refuse a bad name, a taken name and a giveaway computer name', async () => {
      const name = page.getByLabel('GUEST NAME', { exact: true })
      await expect(name).toBeVisible()

      await name.fill('Lab')
      await expect(page.getByText(NAME_RULE)).toBeVisible()
      await expect(continueButton(page)).toBeDisabled()

      await name.fill(TAKEN_NAME)
      await expect(page.getByText(TAKEN_MESSAGE)).toBeVisible()
      await expect(continueButton(page)).toBeDisabled()

      await name.fill(GUEST)
      await expect(page.getByText(TAKEN_MESSAGE)).toHaveCount(0)
      await expect(continueButton(page)).toBeEnabled()

      await page.getByRole('switch', { name: /Microsoft Defender/ }).click()
      await expect(page.getByRole('switch', { name: /Microsoft Defender/ })).toHaveAttribute('aria-checked', 'false')

      await page.getByLabel('USERNAME', { exact: true }).fill('Marta')
      await page.getByLabel('COMPUTER NAME', { exact: true }).fill(GIVEAWAY_COMPUTER_NAME)
      await continueButton(page).click()
      await page.getByRole('button', { name: '[BUILD GUEST]' }).click()

      // The server refuses before anything starts: the form is back on settings, on the computer name.
      await expect(page.getByText(GIVEAWAY_MESSAGE)).toBeVisible()
      await expect(page.getByLabel('GUEST NAME', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '[BUILD GUEST]' })).toHaveCount(0)
      expect(await wizardGuest(request), 'a refused request must not create the guest').toBeUndefined()
    })

    await test.step('(2) [RANDOM] blanks the username and the computer name for the build to choose', async () => {
      for (const label of ['USERNAME', 'COMPUTER NAME']) {
        await identityField(page, label).getByRole('button', { name: '[RANDOM]' }).click()
        await expect(page.getByLabel(label, { exact: true })).toHaveValue('')
        await expect(page.getByLabel(label, { exact: true })).toHaveAttribute('placeholder', RANDOM_PLACEHOLDER)
      }
      await expect(page.getByText(GIVEAWAY_MESSAGE)).toHaveCount(0)
    })

    await test.step('(3) the review shows the chosen values', async () => {
      await continueButton(page).click()
      const review = page.locator('.review')
      await expect(review).toContainText(POLISH_ISO)
      await expect(review).toContainText(GUEST)
      await expect(review).toContainText(/MICROSOFT DEFENDER\s*OFF/)
      await expect(review.locator('.review__value--blank')).toHaveCount(3)
    })

    await test.step('(4) submit hands over to the build page, which shows a step running and a log line', async () => {
      await page.getByRole('button', { name: '[BUILD GUEST]' }).click()
      await expect(page).toHaveURL(BUILD_URL)
      await expect(page.locator('[data-build="header"]')).toContainText(GUEST)
      await expect(page.locator('.build-step[data-status="running"]').first()).toBeVisible({ timeout: BUILD_START_WAIT_MS })
      await expect(page.locator('.build-log__line').first()).toBeVisible({ timeout: BUILD_START_WAIT_MS })
    })

    await test.step('(5) cancelling the build ends it failed with the cancelled message', async () => {
      await page.locator('[data-build="cancel"]').click()
      const dialog = page.locator('.q-dialog')
      await expect(dialog.getByText('Cancel this build?')).toBeVisible()
      await dialog.getByRole('button', { name: 'CANCEL BUILD', exact: true }).click()
      await expect(page.locator('.build-page__failure', { hasText: 'the build was cancelled' })).toBeVisible({ timeout: CANCEL_WAIT_MS })
      await expect(page.getByRole('button', { name: '[RESUME]' })).toBeVisible()
      await expect(page.getByRole('button', { name: '[RESTART]' })).toBeVisible()
      await expect(page.locator('[data-build="cancel"]')).toHaveCount(0)

      const guest = await wizardGuest(request)
      expect(guest?.state).toBe('failed')
      expect(guest?.identity.account, 'the build chose a username for the blank field').toBeTruthy()
      expect(guest?.identity.machine, 'the build chose a computer name for the blank field').toMatch(COMPUTER_NAME_RULE)
      expect(guest?.identity.machine).not.toContain('sandbox')
    })

    await test.step('(6) the Guests page deletes the guest and is back to the original guests', async () => {
      await page.goto('/guest')
      const card = guestCard(page)
      await expect(card).toBeVisible()
      await card.getByRole('button', { name: '[DELETE]' }).click()
      await page.locator('.q-dialog').getByRole('button', { name: 'DELETE', exact: true }).click()
      await expect(card).toHaveCount(0)
      await expect
        .poll(async () => summaryOf((await readGuests(request)).guests), { timeout: STACK_BACK_WAIT_MS })
        .toEqual(originalGuests)
    })
  } finally {
    await removeWizardGuest(request)
  }
})
