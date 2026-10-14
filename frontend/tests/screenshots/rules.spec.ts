import type { Page } from '@playwright/test'
import type { RuleRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  mockRules,
  mockShell,
  screenshotPath,
  test,
  waitForTransitions,
  type RulesMockOptions,
} from './fixtures'
import { INVALID_RULE, LONG_RULE, SCREENSHOT_RULES, UNSUPPORTED_RULE, VALID_SELECTED, yamlOf } from './rules-data'

async function openRules(page: Page, options: Partial<RulesMockOptions> = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockRules(page, { rules: SCREENSHOT_RULES, yaml: yamlOf, ...options })
  await page.goto('/rules')
}

async function listed(page: Page): Promise<void> {
  await expect(page.locator('.rules-table tbody tr').first()).toBeVisible()
}

async function expectTableNotScrolledSideways(page: Page): Promise<void> {
  const { scrollWidth, clientWidth } = await page.locator('.rules-table-scroll').evaluate((table) => ({
    scrollWidth: table.scrollWidth,
    clientWidth: table.clientWidth,
  }))
  expect(scrollWidth, `the table scrolls sideways: ${scrollWidth}px of columns in ${clientWidth}px`).toBeLessThanOrEqual(clientWidth)
}

async function open(page: Page, rule: RuleRead): Promise<void> {
  await page.locator('.rule-row', { hasText: rule.title }).first().click()
  await expect(page.locator('.rule-detail__title')).toHaveText(rule.title)
}

async function snapshot(page: Page, name: string, options: { toast?: boolean } = {}): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  // A toast's progress bar is a finite animation that ends with the toast, so waiting it out would photograph an empty corner.
  if (options.toast) await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  else await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

test('rules-default-list', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await expectNoHorizontalOverflow(page)
  await expectTableNotScrolledSideways(page)
  await expect(page.locator('.rules-count')).toHaveText(`${SCREENSHOT_RULES.length} rules`)
  await snapshot(page, 'rules-default-list')
})

test('rules-selected-valid-rule-with-yaml', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await open(page, VALID_SELECTED)
  await expect(page.locator('.rule-detail__yaml')).toContainText('condition: 1 of selection*')
  await expectNoHorizontalOverflow(page)
  await expectTableNotScrolledSideways(page)
  await snapshot(page, 'rules-selected-valid-rule-with-yaml')
})

test('rules-selected-invalid-rule-with-error', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await open(page, INVALID_RULE)
  await expect(page.locator('.rule-detail__error')).toContainText('selection_img')
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'rules-selected-invalid-rule-with-error')
})

test('rules-selected-unsupported-rule-with-error', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await open(page, UNSUPPORTED_RULE)
  await expect(page.locator('.rule-detail__error')).toContainText('UNSUPPORTED')
  await snapshot(page, 'rules-selected-unsupported-rule-with-error')
})

test('rules-selected-long-title-and-path', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await open(page, LONG_RULE)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'rules-selected-long-title-and-path')
})

test('rules-filtered-by-level', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await page.locator('.filter-select', { hasText: 'LEVEL' }).click()
  await page.getByRole('option', { name: 'CRITICAL' }).click()
  await expect(page.locator('.rules-count')).toContainText('showing')
  await snapshot(page, 'rules-filtered-by-level')
})

test('rules-filtered-by-status-invalid', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await page.locator('.filter-select', { hasText: 'STATUS' }).click()
  await page.getByRole('option', { name: 'INVALID', exact: true }).click()
  await expect(page.locator('.rules-count')).toContainText('showing 1 of')
  await snapshot(page, 'rules-filtered-by-status-invalid')
})

test('rules-filtered-by-text', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await page.locator('.search-input input').fill('custom/')
  await expect(page.locator('.rules-count')).toContainText('showing 4 of')
  await snapshot(page, 'rules-filtered-by-text')
})

test('rules-filtered-no-results-empty', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await page.locator('.search-input input').fill('no such rule anywhere')
  await expect(page.getByText('> no rules match')).toBeVisible()
  await snapshot(page, 'rules-filtered-no-results-empty')
})

test('rules-no-rules-loaded-empty', async ({ page }) => {
  await openRules(page, { rules: [] })
  await expect(page.getByText('> no rules loaded')).toBeVisible()
  await snapshot(page, 'rules-no-rules-loaded-empty')
})

test('rules-loading', async ({ page }) => {
  await openRules(page, { listDelayMs: 4000 })
  await expect(page.locator('.loader')).toBeVisible()
  await snapshot(page, 'rules-loading')
})

test('rules-load-error', async ({ page }) => {
  await openRules(page, { listError: { status: 500, body: errorEnvelope('internal_error', 'The rule registry is unavailable') } })
  await expect(page.getByText('failed to load: The rule registry is unavailable').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await snapshot(page, 'rules-load-error', { toast: true })
})

test('rules-yaml-read-error', async ({ page }) => {
  await openRules(page, { readError: { status: 404, body: errorEnvelope('not_found', 'The file of rule is not available') } })
  await listed(page)
  await page.locator('.rule-row', { hasText: VALID_SELECTED.title }).click()
  await expect(page.locator('.rule-detail').getByText('failed to load')).toBeVisible()
  await snapshot(page, 'rules-yaml-read-error')
})

test('rules-yaml-loading', async ({ page }) => {
  await openRules(page, { readDelayMs: 4000 })
  await listed(page)
  await page.locator('.rule-row', { hasText: VALID_SELECTED.title }).click()
  await expect(page.locator('.rule-detail .loader')).toBeVisible()
  await snapshot(page, 'rules-yaml-loading')
})

test('rules-reload-in-progress', async ({ page }) => {
  await openRules(page, { reloadDelayMs: 4000 })
  await listed(page)
  await page.locator('.reload-btn').click()
  await expect(page.locator('.reload-btn .q-spinner')).toBeVisible()
  await snapshot(page, 'rules-reload-in-progress')
})

test('rules-reload-done-toast', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await page.locator('.reload-btn').click()
  await expect(page.getByText(/Reloaded \d+ rules: 1 invalid, 2 unsupported/)).toBeVisible()
  await snapshot(page, 'rules-reload-done-toast', { toast: true })
})

test('rules-reload-error-toast', async ({ page }) => {
  await openRules(page, { reloadError: { status: 500, body: errorEnvelope('internal_error', 'The rules directory cannot be read') } })
  await listed(page)
  await page.locator('.reload-btn').click()
  await expect(page.getByText('Could not reload the rules')).toBeVisible()
  await snapshot(page, 'rules-reload-error-toast', { toast: true })
})

test('rules-disabled-rule-and-blocked-switch-tooltip', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await page.locator('.rule-row', { hasText: INVALID_RULE.title }).locator('.rule-switch').hover()
  await expect(page.locator('.q-tooltip')).toContainText('Invalid rule, it cannot run')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('rules-disabled-rule-and-blocked-switch-tooltip') })
})

test('rules-switch-save-fails-and-rolls-back', async ({ page }) => {
  await openRules(page, { updateError: { status: 500, body: errorEnvelope('internal_error', 'Could not write the rule state') } })
  await listed(page)
  const row = page.locator('.rule-row', { hasText: VALID_SELECTED.title })
  await row.locator('input[type="checkbox"]').click()
  await expect(page.getByText(`Could not disable ${VALID_SELECTED.title}`)).toBeVisible()
  await expect(row.locator('input[type="checkbox"]')).toBeChecked()
  await snapshot(page, 'rules-switch-save-fails-and-rolls-back', { toast: true })
})

test('rules-keyboard-focus-on-a-row', async ({ page }) => {
  await openRules(page)
  await listed(page)
  await page.locator('.rule-row').nth(2).focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('.rule-detail')).toBeVisible()
  await page.locator('.rule-row').nth(3).focus()
  await page.screenshot({ path: screenshotPath('rules-keyboard-focus-on-a-row'), fullPage: true })
})

test.describe('narrow window', () => {
  test.use({ viewport: { width: 800, height: 900 } })

  test('rules-narrow-800-list', async ({ page }) => {
    await openRules(page)
    await listed(page)
    await expectNoHorizontalOverflow(page)
    await expectTableNotScrolledSideways(page)
    await snapshot(page, 'rules-narrow-800-list')
  })

  test('rules-narrow-800-selected-invalid', async ({ page }) => {
    await openRules(page)
    await listed(page)
    await open(page, INVALID_RULE)
    await expectNoHorizontalOverflow(page)
    await snapshot(page, 'rules-narrow-800-selected-invalid')
  })
})

test.describe('very narrow window', () => {
  test.use({ viewport: { width: 480, height: 900 } })

  test('rules-narrow-480-list', async ({ page }) => {
    await openRules(page)
    await listed(page)
    await expectNoHorizontalOverflow(page)
    await snapshot(page, 'rules-narrow-480-list')
  })
})
