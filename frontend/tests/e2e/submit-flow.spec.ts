import { basename } from 'node:path'
import { expect, test } from '@playwright/test'

const SAMPLE = process.env.E2E_SAMPLE
const ANALYSIS_URL = /\/analyses\/(\d+)/

// Real stack, no mocks. Reaching /analyses/<id> from the dialog proves `useRouter()` works inside
// the Quasar dialog, which the unit tests (a stubbed router) cannot show.
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
    await page.getByRole('button', { name: '▶ DETONATE' }).click()

    await page.waitForURL(ANALYSIS_URL)
    analysisId = ANALYSIS_URL.exec(page.url())?.[1]
    expect(analysisId, 'the URL after submitting carries the analysis id').toBeDefined()

    await expect(page.locator('.status-badge')).toContainText(/done/i, { timeout: 300_000 })
    const score = page.locator('.stat-tile', { hasText: 'SCORE' }).locator('.stat-tile__value')
    await expect(score).toHaveText(/^\d+(\.\d+)?$/)
  } finally {
    if (analysisId) {
      await request.delete(`/api/analyses/${analysisId}`)
    }
  }
})
