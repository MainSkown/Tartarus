import type { Page } from '@playwright/test'
import { GUEST_READY_SYSTEM, expect, expectNoHorizontalOverflow, mockShell, screenshotPath, test, waitForFieldMessages, waitForTransitions } from './fixtures'
import {
  ANALYSIS_ACTIVE_409,
  CONFLICT_409,
  GIVEAWAY_422,
  LONG_MEDIA_FILE,
  MANUAL_STEP_OPTION,
  MEDIA_BROKEN,
  MEDIA_EN,
  MEDIA_LONG_NAME,
  MEDIA_PL,
  MEDIA_UNREAD,
  NAME_TAKEN_422,
  SOURCE_BUILDING,
  SOURCE_DEFENDER_OFF,
  SOURCE_LONG_NAME,
  SOURCE_READY,
  gate,
  mockWizardApi,
  windowsProfile,
  type WizardApiMock,
} from './guest-wizard-data'

const NARROW_WIDTHS = [700, 600]

async function openWizard(page: Page, api: WizardApiMock = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockWizardApi(page, api)
  await page.goto('/guest/new')
}

async function openClone(page: Page, source: string, api: WizardApiMock = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockWizardApi(page, api)
  await page.goto(`/guest/clone/${encodeURIComponent(source)}`)
}

async function snapshot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  await waitForTransitions(page)
  await waitForFieldMessages(page)
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

async function chooseMedium(page: Page, file: string): Promise<void> {
  await page.getByRole('radio', { name: new RegExp(file.slice(0, 20)) }).click()
}

async function continueToSettings(page: Page, file = MEDIA_PL.file): Promise<void> {
  await expect(page.getByRole('radio').first()).toBeVisible()
  await chooseMedium(page, file)
  await page.getByRole('button', { name: '[CONTINUE]' }).click()
  await expect(page.getByLabel('GUEST NAME')).toBeVisible()
}

async function continueToReview(page: Page, name = 'lab5'): Promise<void> {
  await continueToSettings(page)
  await page.getByLabel('GUEST NAME').fill(name)
  await page.getByRole('button', { name: '[CONTINUE]' }).click()
  await expect(page.getByRole('button', { name: '[BUILD GUEST]' })).toBeVisible()
}

test.describe('step 1, choose media', () => {
  test('guest-wizard-media', async ({ page }) => {
    await openWizard(page, { media: [MEDIA_PL, MEDIA_EN, MEDIA_BROKEN, MEDIA_UNREAD] })
    await expect(page.getByRole('radio')).toHaveCount(4)
    await snapshot(page, 'guest-wizard-media')
  })

  for (const width of NARROW_WIDTHS) {
    test(`guest-wizard-media-narrow-${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await openWizard(page, { media: [MEDIA_PL, MEDIA_EN, MEDIA_BROKEN, MEDIA_UNREAD] })
      await expect(page.getByRole('radio')).toHaveCount(4)
      await snapshot(page, `guest-wizard-media-narrow-${width}`)
    })
  }

  test('guest-wizard-media-selected', async ({ page }) => {
    await openWizard(page)
    await chooseMedium(page, MEDIA_PL.file)
    await expect(page.getByRole('radio', { checked: true })).toHaveCount(1)
    await snapshot(page, 'guest-wizard-media-selected')
  })

  test('guest-wizard-media-long-file-name', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openWizard(page, { media: [MEDIA_LONG_NAME, MEDIA_EN] })
    await expect(page.getByRole('radio').first()).toContainText(LONG_MEDIA_FILE)
    await snapshot(page, 'guest-wizard-media-long-file-name')
  })

  test('guest-wizard-media-empty', async ({ page }) => {
    await openWizard(page, { media: [] })
    await expect(page.getByText('> no installation media found')).toBeVisible()
    await snapshot(page, 'guest-wizard-media-empty')
  })

  test('guest-wizard-media-empty-narrow-600', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openWizard(page, { media: [] })
    await expect(page.getByText('> no installation media found')).toBeVisible()
    await snapshot(page, 'guest-wizard-media-empty-narrow-600')
  })

  test('guest-wizard-media-loading', async ({ page }) => {
    const held = gate()
    await openWizard(page, { mediaGate: held.opened })
    await expect(page.locator('.loader')).toBeVisible()
    await snapshot(page, 'guest-wizard-media-loading')
    held.open()
  })

  test('guest-wizard-media-failed', async ({ page }) => {
    await openWizard(page, { mediaFailure: 'The guest control service is not reachable' })
    await expect(page.getByText('> failed to load: The guest control service is not reachable')).toBeVisible()
    await snapshot(page, 'guest-wizard-media-failed')
  })
})

test.describe('step 2, settings', () => {
  test('guest-wizard-settings', async ({ page }) => {
    await openWizard(page)
    await continueToSettings(page)
    await snapshot(page, 'guest-wizard-settings')
  })

  for (const width of NARROW_WIDTHS) {
    test(`guest-wizard-settings-narrow-${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await openWizard(page)
      await continueToSettings(page)
      await snapshot(page, `guest-wizard-settings-narrow-${width}`)
    })
  }

  test('guest-wizard-settings-filled', async ({ page }) => {
    await openWizard(page)
    await continueToSettings(page)
    await page.getByLabel('GUEST NAME').fill('lab5')
    await page.getByLabel('USERNAME').fill('Marta')
    await page.getByLabel('PASSWORD').fill('q7Zp-Lm2x-Rv9d')
    await page.getByRole('button', { name: 'Show' }).first().click()
    await page.getByLabel('PRODUCT KEY').fill('AAAAA-BBBBB-CCCCC-DDDDD-EEEEE')
    await page.getByRole('switch', { name: /Microsoft Defender/ }).click()
    await snapshot(page, 'guest-wizard-settings-filled')
  })

  test('guest-wizard-settings-invalid-name', async ({ page }) => {
    await openWizard(page)
    await continueToSettings(page)
    await page.getByLabel('GUEST NAME').fill('My Lab')
    await page.getByLabel('USERNAME').fill('two words')
    await expect(page.getByRole('button', { name: '[CONTINUE]' })).toBeDisabled()
    await snapshot(page, 'guest-wizard-settings-invalid-name')
  })

  test('guest-wizard-settings-edition-open', async ({ page }) => {
    await openWizard(page)
    await continueToSettings(page)
    await page.getByLabel('EDITION').click()
    await expect(page.getByRole('option', { name: /Windows 11 Pro N/ })).toBeVisible()
    await snapshot(page, 'guest-wizard-settings-edition-open')
  })

  test('guest-wizard-settings-keyboard-open', async ({ page }) => {
    await openWizard(page)
    await continueToSettings(page)
    await page.getByLabel('KEYBOARD LAYOUT').click()
    await expect(page.getByRole('option', { name: 'Ukrainian' })).toBeVisible()
    await snapshot(page, 'guest-wizard-settings-keyboard-open')
  })

  test('guest-wizard-settings-manual-step-option', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openWizard(page, { profiles: [windowsProfile([...windowsProfile().options, MANUAL_STEP_OPTION])] })
    await continueToSettings(page)
    await expect(page.getByText('may ask for one manual step')).toBeVisible()
    await snapshot(page, 'guest-wizard-settings-manual-step-option-narrow-600')
  })

  test('guest-wizard-settings-long-values', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openWizard(page, { media: [MEDIA_LONG_NAME] })
    await continueToSettings(page, LONG_MEDIA_FILE)
    await page.getByLabel('GUEST NAME').fill('a-very-long-guest-name-that-goes-on-and-on-1')
    await page.getByLabel('USERNAME').fill('AnExtremelyLongUsernameThatIsTooLong')
    await page.getByLabel('PASSWORD').fill('x'.repeat(70))
    await page.getByLabel('PRODUCT KEY').fill('Z'.repeat(60))
    await snapshot(page, 'guest-wizard-settings-long-values-narrow-600')
  })

  test('guest-wizard-settings-single-edition-no-select', async ({ page }) => {
    await openWizard(page)
    await continueToSettings(page, MEDIA_EN.file)
    await expect(page.getByLabel('EDITION')).toBeVisible()
    await snapshot(page, 'guest-wizard-settings-single-edition')
  })
})

test.describe('step 3, review and submit', () => {
  test('guest-wizard-review', async ({ page }) => {
    await openWizard(page)
    await continueToReview(page)
    await snapshot(page, 'guest-wizard-review')
  })

  test('guest-wizard-review-chosen-identity', async ({ page }) => {
    await openWizard(page)
    await continueToSettings(page)
    await page.getByLabel('GUEST NAME').fill('lab5')
    await page.getByLabel('USERNAME').fill('Marta')
    await page.getByLabel('COMPUTER NAME').fill('LAPTOP-9HD3M1P')
    await page.getByRole('button', { name: '[CONTINUE]' }).click()
    await expect(page.getByRole('button', { name: '[BUILD GUEST]' })).toBeVisible()
    await snapshot(page, 'guest-wizard-review-chosen-identity')
  })

  for (const width of NARROW_WIDTHS) {
    test(`guest-wizard-review-narrow-${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await openWizard(page, { media: [MEDIA_LONG_NAME] })
      await continueToSettings(page, LONG_MEDIA_FILE)
      await page.getByLabel('GUEST NAME').fill('lab5')
      await page.getByRole('button', { name: '[CONTINUE]' }).click()
      await expect(page.getByRole('button', { name: '[BUILD GUEST]' })).toBeVisible()
      await snapshot(page, `guest-wizard-review-narrow-${width}`)
    })
  }

  test('guest-wizard-submitting', async ({ page }) => {
    const held = gate()
    await openWizard(page, { startGate: held.opened })
    await continueToReview(page)
    await page.getByRole('button', { name: '[BUILD GUEST]' }).click()
    await expect(page.getByRole('button', { name: '[BACK]' })).toBeDisabled()
    await snapshot(page, 'guest-wizard-submitting')
    held.open()
  })

  test('guest-wizard-review-conflict-409-build-running', async ({ page }) => {
    await openWizard(page, { startRefusal: { status: 409, body: CONFLICT_409 } })
    await continueToReview(page)
    await page.getByRole('button', { name: '[BUILD GUEST]' }).click()
    await expect(page.getByRole('alert')).toContainText('Another guest is being built')
    await snapshot(page, 'guest-wizard-review-conflict-409')
  })

  test('guest-wizard-review-conflict-409-narrow-600', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openWizard(page, { startRefusal: { status: 409, body: ANALYSIS_ACTIVE_409 } })
    await continueToReview(page)
    await page.getByRole('button', { name: '[BUILD GUEST]' }).click()
    await expect(page.getByRole('alert')).toContainText('An analysis is queued or running')
    await snapshot(page, 'guest-wizard-review-conflict-409-narrow-600')
  })

  test('guest-wizard-giveaway-422-jumps-back', async ({ page }) => {
    await openWizard(page, { startRefusal: { status: 422, body: GIVEAWAY_422 } })
    await continueToSettings(page)
    await page.getByLabel('GUEST NAME').fill('lab5')
    await page.getByLabel('COMPUTER NAME').fill('TEST-PC')
    await page.getByRole('button', { name: '[CONTINUE]' }).click()
    await page.getByRole('button', { name: '[BUILD GUEST]' }).click()
    await expect(page.getByText("contains 'test'")).toBeVisible()
    await expect(page.getByLabel('GUEST NAME')).toBeVisible()
    await snapshot(page, 'guest-wizard-giveaway-422-jumps-back')
  })

  test('guest-wizard-giveaway-422-narrow-600', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openWizard(page, { startRefusal: { status: 422, body: GIVEAWAY_422 } })
    await continueToSettings(page)
    await page.getByLabel('GUEST NAME').fill('lab5')
    await page.getByLabel('COMPUTER NAME').fill('TEST-PC')
    await page.getByRole('button', { name: '[CONTINUE]' }).click()
    await page.getByRole('button', { name: '[BUILD GUEST]' }).click()
    await expect(page.getByText("contains 'test'")).toBeVisible()
    await snapshot(page, 'guest-wizard-giveaway-422-narrow-600')
  })

  test('guest-wizard-name-taken-422', async ({ page }) => {
    await openWizard(page, { startRefusal: { status: 422, body: NAME_TAKEN_422 } })
    await continueToReview(page)
    await page.getByRole('button', { name: '[BUILD GUEST]' }).click()
    await expect(page.getByText('is already used by another guest')).toBeVisible()
    await snapshot(page, 'guest-wizard-name-taken-422')
  })
})

test.describe('the clone form', () => {
  const GUESTS = [SOURCE_READY, SOURCE_DEFENDER_OFF, SOURCE_BUILDING]

  test('guest-clone-form', async ({ page }) => {
    await openClone(page, 'lab2', { guests: GUESTS })
    await expect(page.getByRole('button', { name: '[CLONE]' })).toBeVisible()
    await snapshot(page, 'guest-clone-form')
  })

  for (const width of NARROW_WIDTHS) {
    test(`guest-clone-form-narrow-${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await openClone(page, 'lab2', { guests: GUESTS })
      await expect(page.getByRole('button', { name: '[CLONE]' })).toBeVisible()
      await snapshot(page, `guest-clone-form-narrow-${width}`)
    })
  }

  test('guest-clone-form-filled', async ({ page }) => {
    await openClone(page, 'lab1', { guests: GUESTS })
    await page.getByLabel('NEW NAME').fill('lab6')
    await page.getByLabel('COMPUTER NAME').fill('LAPTOP-9HD3M1P')
    await page.getByRole('switch', { name: /Microsoft Defender/ }).click()
    await expect(page.getByRole('button', { name: '[CLONE]' })).toBeEnabled()
    await snapshot(page, 'guest-clone-form-filled')
  })

  test('guest-clone-form-invalid-name', async ({ page }) => {
    await openClone(page, 'lab1', { guests: GUESTS })
    await page.getByLabel('NEW NAME').fill('lab2')
    await page.getByLabel('COMPUTER NAME').fill('-bad-')
    await expect(page.getByRole('button', { name: '[CLONE]' })).toBeDisabled()
    await snapshot(page, 'guest-clone-form-invalid-name')
  })

  test('guest-clone-form-long-source-name', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openClone(page, SOURCE_LONG_NAME.name, { guests: [SOURCE_LONG_NAME] })
    await expect(page.getByRole('button', { name: '[CLONE]' })).toBeVisible()
    await snapshot(page, 'guest-clone-form-long-source-name-narrow-600')
  })

  test('guest-clone-source-not-found', async ({ page }) => {
    await openClone(page, 'nobody', { guests: GUESTS })
    await expect(page.getByText('There is no guest called nobody.')).toBeVisible()
    await snapshot(page, 'guest-clone-source-not-found')
  })

  test('guest-clone-source-not-ready', async ({ page }) => {
    await openClone(page, 'lab4', { guests: GUESTS })
    await expect(page.getByText('lab4 is building')).toBeVisible()
    await snapshot(page, 'guest-clone-source-not-ready')
  })

  test('guest-clone-source-not-ready-narrow-600', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openClone(page, 'lab4', { guests: GUESTS })
    await expect(page.getByText('lab4 is building')).toBeVisible()
    await snapshot(page, 'guest-clone-source-not-ready-narrow-600')
  })

  test('guest-clone-loading', async ({ page }) => {
    const held = gate()
    await openClone(page, 'lab1', { guests: GUESTS, listGate: held.opened })
    await snapshot(page, 'guest-clone-loading')
    held.open()
  })

  test('guest-clone-giveaway-422', async ({ page }) => {
    await openClone(page, 'lab1', { guests: GUESTS, startRefusal: { status: 422, body: GIVEAWAY_422 } })
    await page.getByLabel('NEW NAME').fill('lab6')
    await page.getByLabel('COMPUTER NAME').fill('TEST-PC')
    await page.getByRole('button', { name: '[CLONE]' }).click()
    await expect(page.getByText("contains 'test'")).toBeVisible()
    await snapshot(page, 'guest-clone-giveaway-422')
  })

  test('guest-clone-conflict-409-narrow-600', async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 })
    await openClone(page, 'lab1', { guests: GUESTS, startRefusal: { status: 409, body: CONFLICT_409 } })
    await page.getByLabel('NEW NAME').fill('lab6')
    await page.getByRole('button', { name: '[CLONE]' }).click()
    await expect(page.getByRole('alert')).toContainText('Another guest is being built')
    await snapshot(page, 'guest-clone-conflict-409-narrow-600')
  })

  test('guest-clone-submitting', async ({ page }) => {
    const held = gate()
    await openClone(page, 'lab1', { guests: GUESTS, startGate: held.opened })
    await page.getByLabel('NEW NAME').fill('lab6')
    await page.getByRole('button', { name: '[CLONE]' }).click()
    await expect(page.locator('.clone-submit .q-spinner')).toBeVisible()
    await snapshot(page, 'guest-clone-submitting')
    held.open()
  })
})
