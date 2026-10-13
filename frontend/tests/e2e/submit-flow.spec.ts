import { basename } from 'node:path'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const SAMPLE = process.env.E2E_SAMPLE
const ANALYSIS_URL = /\/analyses\/(\d+)/

const openTab = (page: Page, label: string) => page.getByRole('tab', { name: label, exact: true }).click()

async function expectOverviewContent(page: Page): Promise<void> {
  await expect(page.locator('.lane-bar').first()).toBeVisible()
  const thumbnail = page.locator('.screenshot-strip__thumb img').first()
  await thumbnail.scrollIntoViewIfNeeded()
  // Soft: a broken image must not hide what the other tabs show.
  await expect
    .configure({ soft: true })
    .poll(() => thumbnail.evaluate((image: HTMLImageElement) => image.naturalWidth), {
      message: 'the first screenshot thumbnail must have loaded, not only been rendered',
    })
    .toBeGreaterThan(0)
}

async function expectProcessesContent(page: Page, processName: string): Promise<void> {
  await openTab(page, 'PROCESSES')
  await expect(page.locator('.process-graph__canvas')).toBeVisible()
  await expect(page.locator('.process-details__title')).toContainText(processName)
}

async function expectNetworkContent(page: Page): Promise<void> {
  await openTab(page, 'NETWORK')
  await expect(page.getByRole('tab', { name: /^DNS \(\d+\)$/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.network-table tbody tr').first()).toBeVisible()
}

async function expectArtifactsContent(page: Page, request: APIRequestContext, analysisId: string): Promise<void> {
  const listing = await request.get(`/api/analyses/${analysisId}/artifacts`)
  const dropped = (await listing.json()).dropped[0]
  expect(dropped, 'the analysis must have dropped a file').toBeDefined()

  await openTab(page, 'ARTIFACTS')
  const row = page.locator('.artifact-table tbody tr', { hasText: dropped.name }).first()
  await expect(row).toBeVisible()
  await expect(row.getByRole('link', { name: /DOWNLOAD/ })).toHaveAttribute(
    'href',
    `/api/analyses/${analysisId}/artifacts/${dropped.id}/download`,
  )
}

async function expectDetectionsContent(page: Page): Promise<void> {
  await openTab(page, 'DETECTIONS')
  await expect(page.locator('.detection-entry').first()).toBeVisible()
  await page.locator('label[for="detections-mode-attack"]').click()
  await expect(page.locator('.attack-cell').first()).toBeVisible()
}

// Real stack, no mocks. Reaching /analyses/<id> from the dialog proves `useRouter()` works inside
// the Quasar dialog, which the unit tests (a stubbed router) cannot show. Once the analysis is
// done, every exploring tab must show what the real index and report hold.
test('submit a sample through the dialog and watch it finish', async ({ page, request }) => {
  test.skip(!SAMPLE, 'E2E_SAMPLE must name the file to submit; scripts/e2e.sh sets it')
  const sample = SAMPLE as string
  let analysisId: string | undefined

  try {
    await page.goto('/')
    const submit = page.getByRole('button', { name: '+ SUBMIT', exact: true })
    await expect(submit, 'the guest must be ready for the header button to be enabled').toBeEnabled()
    await submit.click()

    await page.locator('input[type="file"]').setInputFiles(sample)
    await expect(page.locator('.file-name')).toHaveText(basename(sample))
    // An interactive run lasts its whole timeout; the desktop flow covers those, this one wants the finished views.
    const interactive = page.getByRole('switch', { name: 'INTERACTIVE DESKTOP' })
    if ((await interactive.getAttribute('aria-checked')) === 'true') await interactive.click()
    await expect(interactive).toHaveAttribute('aria-checked', 'false')
    await page.getByRole('button', { name: '▶ DETONATE' }).click()

    await page.waitForURL(ANALYSIS_URL)
    analysisId = ANALYSIS_URL.exec(page.url())?.[1]
    expect(analysisId, 'the URL after submitting carries the analysis id').toBeDefined()

    // The LIVE tab shows a second badge while the analysis is active; the first is the page header's.
    await expect(page.locator('.status-badge').first()).toContainText(/done/i, { timeout: 300_000 })
    // A finished analysis keeps the LIVE tab it opened on; its views start at SUMMARY.
    await openTab(page, 'SUMMARY')
    const score = page.locator('.stat-tile', { hasText: 'SCORE' }).locator('.stat-tile__value')
    await expect(score).toHaveText(/^\d+(\.\d+)?$/)

    await expectOverviewContent(page)
    await expectProcessesContent(page, basename(sample))
    await expectNetworkContent(page)
    await expectArtifactsContent(page, request, analysisId as string)
    await expectDetectionsContent(page)
  } finally {
    if (analysisId) {
      await request.delete(`/api/analyses/${analysisId}`)
    }
  }
})
