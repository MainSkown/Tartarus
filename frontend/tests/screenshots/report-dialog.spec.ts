import type { Page } from '@playwright/test'
import {
  ANALYSIS_ID,
  DONE_PDF,
  FINISHED_ANALYSIS,
  JOB_ID,
  openAnalysis,
  reportJob,
  snapshot,
  type ExportsMock,
} from './export-mock'
import { errorEnvelope, expect, expectNoHorizontalOverflow, test, waitForTransitions } from './fixtures'

const LONG_FILENAME = `quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo_and_cfo_${'x'.repeat(60)}.pdf.exe`

async function openDialog(page: Page, format: 'HTML' | 'PDF' = 'PDF'): Promise<void> {
  await page.getByRole('button', { name: '[EXPORT]' }).click()
  await page.locator('.export-entries .q-item', { hasText: new RegExp(`^${format}$`) }).click()
  await expect(page.locator('.report-dialog')).toBeVisible()
}

async function generate(page: Page): Promise<void> {
  await page.getByRole('button', { name: '[GENERATE]' }).click()
  await expect(page.locator('.report-dialog progress')).toBeVisible()
}

async function startGenerating(page: Page, exports: ExportsMock): Promise<void> {
  await openDialog(page)
  await generate(page)
  exports.pushJob({ status: 'running', progress: 0, step: 'Reading the analysis files' })
  await expect(page.locator('.report-dialog__step')).toHaveText('Reading the analysis files')
}

async function progressTo(page: Page, exports: ExportsMock, progress: number, step: string): Promise<void> {
  exports.pushJob({ status: 'running', progress, step })
  await expect(page.locator('.report-dialog__percent')).toHaveText(`${progress}%`)
}

const dialog = (page: Page) => page.locator('.report-dialog')

// ---------- The form ----------

test('report-dialog-default-pdf', async ({ page }) => {
  await openAnalysis(page)
  await openDialog(page, 'PDF')
  await expect(page.locator('input[name="format"][value="pdf"]')).toBeChecked()
  await snapshot(page, 'dialog-01-default-pdf', { fullPage: false })
})

test('report-dialog-default-html', async ({ page }) => {
  await openAnalysis(page)
  await openDialog(page, 'HTML')
  await expect(page.locator('input[name="format"][value="html"]')).toBeChecked()
  await snapshot(page, 'dialog-02-default-html', { fullPage: false })
})

test('report-dialog-options-changed', async ({ page }) => {
  await openAnalysis(page)
  await openDialog(page, 'PDF')
  await page.locator('label[for="report-format-html"]').click()
  await page.locator('input[name="notes"]').uncheck()
  await page.locator('input[name="raw_iocs"]').uncheck()
  await snapshot(page, 'dialog-03-options-changed', { fullPage: false })
})

test('report-dialog-submits-exactly-what-was-chosen', async ({ page }) => {
  const exports = await openAnalysis(page)
  await openDialog(page, 'PDF')
  await page.locator('label[for="report-format-html"]').click()
  await page.locator('input[name="screenshots"]').uncheck()
  await generate(page)
  expect(exports.reportRequests()).toEqual([{ format: 'html', include: { notes: true, screenshots: false, raw_iocs: true } }])
})

test('report-dialog-long-filename-in-the-title', async ({ page }) => {
  await openAnalysis(page, { ...FINISHED_ANALYSIS, filename: LONG_FILENAME })
  await openDialog(page)
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
  const card = (await dialog(page).boundingBox())!
  const title = (await page.locator('.report-dialog__title').boundingBox())!
  expect(title.x + title.width, 'the title stays inside the dialog').toBeLessThanOrEqual(card.x + card.width)
  await snapshot(page, 'dialog-04-long-filename-title', { fullPage: false })
})

test('report-dialog-409-error-inline', async ({ page }) => {
  await openAnalysis(page, FINISHED_ANALYSIS, {
    reportReply: { status: 409, body: errorEnvelope('conflict', 'Analysis 193 is not finished yet: it is ingesting') },
  })
  await openDialog(page)
  await page.getByRole('button', { name: '[GENERATE]' }).click()
  await expect(dialog(page).getByRole('alert')).toHaveText('Analysis 193 is not finished yet: it is ingesting')
  await expect(page.locator('.tt-toast--error')).toHaveCount(0)
  await snapshot(page, 'dialog-05-409-error-inline', { fullPage: false })
})

test('report-dialog-422-error-inline', async ({ page }) => {
  await openAnalysis(page, FINISHED_ANALYSIS, {
    reportReply: {
      status: 422,
      body: {
        error: {
          code: 'validation_error',
          message: 'Request validation failed',
          details: { fields: [{ location: ['body', 'format'], message: "Input should be 'html' or 'pdf'", type: 'enum' }] },
        },
      },
    },
  })
  await openDialog(page)
  await page.getByRole('button', { name: '[GENERATE]' }).click()
  await expect(dialog(page).getByRole('alert')).toHaveText("Input should be 'html' or 'pdf'")
  await snapshot(page, 'dialog-06-422-error-inline', { fullPage: false })
})

// ---------- Generating ----------

test('report-dialog-generating-0', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  await expect(page.locator('.report-dialog__percent')).toHaveText('0%')
  await snapshot(page, 'dialog-07-generating-0', { fullPage: false })
})

test('report-dialog-generating-45', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  await progressTo(page, exports, 45, 'Collecting the indicators')
  await snapshot(page, 'dialog-08-generating-45', { fullPage: false })
})

test('report-dialog-generating-99', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  await progressTo(page, exports, 99, 'Saving the file')
  await snapshot(page, 'dialog-09-generating-99', { fullPage: false })
})

test('report-dialog-done-download', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  exports.pushJob(DONE_PDF)
  await expect(page.getByRole('button', { name: '[DOWNLOAD PDF]' })).toBeVisible()
  await snapshot(page, 'dialog-10-done-download', { fullPage: false })

  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: '[DOWNLOAD PDF]' }).click()
  expect((await downloading).suggestedFilename()).toBe(`tartarus-report-${ANALYSIS_ID}.pdf`)
})

test('report-dialog-failed-with-reason-and-retry', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  exports.pushJob({ status: 'failed', progress: 85, step: 'Assembling the report', result: { error: 'WeasyPrint ran out of memory while laying out page 212 of the report' } })
  await expect(dialog(page).getByRole('alert')).toContainText('WeasyPrint ran out of memory')
  await snapshot(page, 'dialog-11-failed-reason-retry', { fullPage: false })

  exports.nextJobId(JOB_ID + 1)
  await page.getByRole('button', { name: '[RETRY]' }).click()
  await expect(page.locator('.report-dialog progress')).toBeVisible()
  expect(exports.reportRequests()).toHaveLength(2)
  expect(exports.reportRequests()[1]).toEqual(exports.reportRequests()[0])
})

test('report-dialog-interrupted', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  exports.pushJob({ status: 'interrupted', progress: 40, step: 'Reading the network activity' })
  await expect(dialog(page).getByRole('alert')).toContainText('backend restarted')
  await snapshot(page, 'dialog-12-interrupted', { fullPage: false })
})

// ---------- Closed while running ----------

test('report-dialog-reopened-while-running-shows-the-progress', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  await progressTo(page, exports, 45, 'Collecting the indicators')
  await page.getByRole('button', { name: 'CLOSE' }).click()
  await expect(dialog(page)).toBeHidden()

  await openDialog(page, 'HTML')
  await expect(page.locator('.report-dialog__percent')).toHaveText('45%')
  expect(exports.reportRequests()).toHaveLength(1)
  await snapshot(page, 'dialog-13-reopened-while-running', { fullPage: false })
})

test('report-dialog-closed-while-running-then-report-ready-toast', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  await page.getByRole('button', { name: 'CLOSE' }).click()
  await expect(dialog(page)).toBeHidden()

  exports.pushJob(DONE_PDF)
  await expect(page.locator('.tt-toast--success')).toContainText('Report ready')
  await snapshot(page, 'dialog-14-report-ready-toast', { fullPage: false, toast: true })

  const downloading = page.waitForEvent('download')
  await page.locator('.tt-toast--success').getByRole('button', { name: 'DOWNLOAD' }).click()
  expect((await downloading).suggestedFilename()).toBe(`tartarus-report-${ANALYSIS_ID}.pdf`)
})

test('report-dialog-open-while-finishing-shows-no-toast', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  exports.pushJob(DONE_PDF)
  await expect(page.getByRole('button', { name: '[DOWNLOAD PDF]' })).toBeVisible()
  await expect(page.locator('.tt-toast')).toHaveCount(0)
})

test('report-dialog-closed-while-running-then-failed-toast', async ({ page }) => {
  const exports = await openAnalysis(page)
  await startGenerating(page, exports)
  await page.getByRole('button', { name: 'CLOSE' }).click()
  await expect(dialog(page)).toBeHidden()
  exports.pushJob({ status: 'failed', progress: 85, result: { error: 'WeasyPrint ran out of memory' } })
  await expect(page.locator('.tt-toast--error')).toContainText('Report failed')
  await snapshot(page, 'dialog-15-report-failed-toast', { fullPage: false, toast: true })
})

// ---------- Narrow window ----------

test('report-dialog-narrow-800', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 700 })
  const exports = await openAnalysis(page, { ...FINISHED_ANALYSIS, filename: LONG_FILENAME })
  await openDialog(page)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'dialog-16-narrow-800-form', { fullPage: false })

  await generate(page)
  exports.pushJob({ status: 'running', progress: 45, step: 'Collecting the indicators' })
  await expect(page.locator('.report-dialog__percent')).toHaveText('45%')
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'dialog-17-narrow-800-generating', { fullPage: false })

  exports.pushJob({ ...reportJob(DONE_PDF) })
  await expect(page.getByRole('button', { name: '[DOWNLOAD PDF]' })).toBeVisible()
  await snapshot(page, 'dialog-18-narrow-800-done', { fullPage: false })
})

test('report-dialog-narrow-380-phone', async ({ page }) => {
  await page.setViewportSize({ width: 380, height: 700 })
  const exports = await openAnalysis(page)
  await openDialog(page)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'dialog-19-narrow-380-form', { fullPage: false })
  await generate(page)
  exports.pushJob({ status: 'failed', progress: 85, result: { error: 'WeasyPrint ran out of memory while laying out page 212 of the report' } })
  await expect(dialog(page).getByRole('alert')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'dialog-20-narrow-380-failed', { fullPage: false })
})
