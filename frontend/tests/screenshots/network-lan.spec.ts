import type { Page } from '@playwright/test'
import { GUEST_READY_SYSTEM, expect, expectNoHorizontalOverflow, makeDetectedAnalysis, mockAnalyses, mockShell, mockViews, screenshotPath, test, waitForTransitions, type ViewMock } from './fixtures'
import { DOMAIN_CONTROLLER, FILE_SERVER, LONG_FAKE_HOSTS, MIXED_HOSTS, NO_FAKE_HOSTS, ONLY_FAKE_HOSTS, flowsView, hostsView } from './network-lan-data'

const ID = 45
const FILTER_ON_SIMULATED = 'Filter on tartarus.lan.simulated: true'

async function openNetwork(page: Page, network: ViewMock, subTab: string): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockViews(page, { network })
  await page.goto(`/analyses/${ID}/network`)
  await expect(page.getByRole('tab', { name: /^DNS/ })).toBeVisible()
  await page.getByRole('tab', { name: new RegExp(`^${subTab}`) }).click()
  await waitForTransitions(page)
}

test('network-lan-hosts-mixed', async ({ page }) => {
  await openNetwork(page, hostsView(MIXED_HOSTS), 'HOSTS')
  await expect(page.locator('.fake-lan-badge')).toHaveCount(3)
  await page.screenshot({ path: screenshotPath('network-lan-hosts-mixed'), fullPage: true })
})

test('network-lan-hosts-only-fake', async ({ page }) => {
  await openNetwork(page, hostsView(ONLY_FAKE_HOSTS), 'HOSTS')
  await expect(page.locator('.fake-lan-badge')).toHaveCount(3)
  await page.screenshot({ path: screenshotPath('network-lan-hosts-only-fake'), fullPage: true })
})

test('network-lan-hosts-no-fake', async ({ page }) => {
  await openNetwork(page, hostsView(NO_FAKE_HOSTS), 'HOSTS')
  await expect(page.locator('.fake-lan-badge')).toHaveCount(0)
  await page.screenshot({ path: screenshotPath('network-lan-hosts-no-fake'), fullPage: true })
})

test('network-lan-hosts-long-values', async ({ page }) => {
  await openNetwork(page, hostsView(LONG_FAKE_HOSTS), 'HOSTS')
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('network-lan-hosts-long-values'), fullPage: true })
})

test('network-lan-hosts-narrow-360', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await openNetwork(page, hostsView([...LONG_FAKE_HOSTS, FILE_SERVER, DOMAIN_CONTROLLER]), 'HOSTS')
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('network-lan-hosts-narrow-360'), fullPage: true })
})

test('network-lan-hosts-filter-on', async ({ page }) => {
  await openNetwork(page, hostsView(MIXED_HOSTS), 'HOSTS')
  await page.getByRole('button', { name: FILTER_ON_SIMULATED }).first().click()
  await expect(page.getByRole('button', { name: FILTER_ON_SIMULATED }).first()).toBeVisible()
  await page.screenshot({ path: screenshotPath('network-lan-hosts-filter-on'), fullPage: true })
})

test('network-lan-flows', async ({ page }) => {
  await openNetwork(page, flowsView(), 'FLOWS')
  await expect(page.locator('.fake-lan-badge')).toHaveCount(2)
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('network-lan-flows'), fullPage: true })
})
