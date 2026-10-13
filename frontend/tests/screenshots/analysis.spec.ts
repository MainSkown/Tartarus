import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeAnalysis,
  makeCleanAnalysis,
  makeDetectedAnalysis,
  mockAnalyses,
  mockShell,
  screenshotPath,
  test,
  waitForTransitions,
  type AnalysesMockOptions,
} from './fixtures'

test.use({ timezoneId: 'UTC' })

const ID = 7
const STARTED_AT = '2026-10-12T09:14:30Z'
const LONG_FILENAME = `quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo_and_cfo_${'x'.repeat(80)}.pdf.exe`
const LONG_ERROR = `CAPE task 107 aborted: ${'the guest agent stopped answering while the sample was spawning child processes, '.repeat(4)}C:\\Users\\Administrator\\AppData\\Local\\Temp\\${'nested_'.repeat(20)}error.log`

async function openAnalysis(page: Page, analysis: AnalysisRead | undefined, mock: Partial<AnalysesMockOptions> = {}, path = `/analyses/${ID}`): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: analysis ? [analysis] : [], ...mock })
  await page.goto(path)
}

async function expectHeaderShowing(page: Page, analysis: AnalysisRead): Promise<void> {
  await expect(page.locator('.analysis-header__filename')).toHaveText(analysis.filename)
  await waitForTransitions(page)
}

const STATE_SCENARIOS: { name: string; analysis: AnalysisRead; text: string }[] = [
  { name: 'analysis-queued', analysis: makeAnalysis({ id: ID, status: 'queued' }), text: 'queued, waiting for the guest to be free' },
  { name: 'analysis-running', analysis: makeAnalysis({ id: ID, status: 'running', started_at: STARTED_AT }), text: 'detonating in the guest' },
  { name: 'analysis-processing', analysis: makeAnalysis({ id: ID, status: 'processing', started_at: STARTED_AT }), text: 'CAPE is processing the results' },
  { name: 'analysis-done-detections', analysis: makeDetectedAnalysis({ id: ID }), text: 'SIGNATURES' },
  { name: 'analysis-done-clean', analysis: makeCleanAnalysis({ id: ID }), text: 'no detections: CAPE raised no signatures' },
  {
    name: 'analysis-failed',
    analysis: makeAnalysis({ id: ID, status: 'failed', started_at: STARTED_AT, error: 'CAPE could not start the guest: the VM snapshot "clean" is missing' }),
    text: 'ANALYSIS FAILED',
  },
  {
    name: 'analysis-report-failed',
    analysis: makeAnalysis({ id: ID, status: 'report_failed', started_at: STARTED_AT, error: 'report.json was truncated at byte 4194304' }),
    text: 'REPORT FAILED',
  },
  { name: 'analysis-cancelled', analysis: makeAnalysis({ id: ID, status: 'cancelled' }), text: 'cancelled before it ran' },
]

test('the header Submit button and the page actions share a right edge', async ({ page }) => {
  const analysis = makeDetectedAnalysis({ id: ID })
  await openAnalysis(page, analysis)
  await expectHeaderShowing(page, analysis)
  const submit = await page.getByRole('button', { name: '+ SUBMIT', exact: true }).boundingBox()
  const remove = await page.locator('.analysis-header__delete').boundingBox()
  expect(Math.round(submit!.x + submit!.width)).toBe(Math.round(remove!.x + remove!.width))
})

for (const { name, analysis, text } of STATE_SCENARIOS) {
  test(name, async ({ page }) => {
    await openAnalysis(page, analysis)
    await expectHeaderShowing(page, analysis)
    await expect(page.getByText(text, { exact: false }).first()).toBeVisible()
    await page.screenshot({ path: screenshotPath(name), fullPage: true })
  })
}

test('analysis-load-error', async ({ page }) => {
  await openAnalysis(page, undefined, { oneError: { status: 500, body: errorEnvelope('internal_error', 'database connection lost') } })
  await expect(page.getByText('failed to load: database connection lost')).toBeVisible()
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await page.screenshot({ path: screenshotPath('analysis-load-error') })
})

test('analysis-not-found', async ({ page }) => {
  await openAnalysis(page, undefined, {}, '/analyses/999')
  await expect(page.getByText('failed to load: Analysis 999 not found')).toBeVisible()
  await page.screenshot({ path: screenshotPath('analysis-not-found') })
})

test('analysis-invalid-id', async ({ page }) => {
  await openAnalysis(page, undefined, {}, '/analyses/not-a-number')
  await expect(page.getByText('analysis not found')).toBeVisible()
  await page.screenshot({ path: screenshotPath('analysis-invalid-id') })
})

test('analysis-loading', async ({ page }) => {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })], oneDelayMs: 3000 })
  await page.goto(`/analyses/${ID}`)
  await expect(page.locator('.loader')).toBeVisible()
  await page.screenshot({ path: screenshotPath('analysis-loading') })
})

test('analysis-long-text', async ({ page }) => {
  const analysis = makeAnalysis({ id: ID, status: 'failed', filename: LONG_FILENAME, started_at: STARTED_AT, error: LONG_ERROR })
  await openAnalysis(page, analysis)
  await expectHeaderShowing(page, analysis)
  await expect(page.getByRole('alert')).toContainText('CAPE task 107 aborted')
  await page.screenshot({ path: screenshotPath('analysis-long-text'), fullPage: true })
})

function makeLongDetectedAnalysis(): AnalysisRead {
  const base = makeDetectedAnalysis({ id: ID, filename: LONG_FILENAME })
  return {
    ...base,
    detected_families: [...base.detected_families, 'A_family_with_a_very_long_name_that_keeps_going_and_going_without_any_break_at_all'],
    summary: {
      ...base.summary,
      signatures: [
        ...base.summary!.signatures!,
        { name: `signature_${'with_a_very_long_unbroken_name_'.repeat(4)}`, severity: 'high', description: `${'Detects extremely verbose behaviour '.repeat(10)}end` },
      ],
    },
  }
}

test('analysis-long-detections', async ({ page }) => {
  const analysis = makeLongDetectedAnalysis()
  await openAnalysis(page, analysis)
  await expectHeaderShowing(page, analysis)
  await expect(page.getByText('with_a_very_long_unbroken_name_', { exact: false })).toBeVisible()
  await page.screenshot({ path: screenshotPath('analysis-long-detections'), fullPage: true })
})

test('analysis-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 800 })
  const analysis = makeDetectedAnalysis({ id: ID, filename: LONG_FILENAME })
  await openAnalysis(page, analysis)
  await expectHeaderShowing(page, analysis)
  await page.screenshot({ path: screenshotPath('analysis-narrow-600'), fullPage: true })
})

test('analysis-unbuilt-tab', async ({ page }) => {
  const analysis = makeDetectedAnalysis({ id: ID })
  await openAnalysis(page, analysis, {}, `/analyses/${ID}/events`)
  await expect(page.getByText('events arrives with M1b')).toBeVisible()
  await page.screenshot({ path: screenshotPath('analysis-unbuilt-tab') })
})

test('analysis tabs not built yet are disabled and say when they arrive', async ({ page }) => {
  await openAnalysis(page, makeDetectedAnalysis({ id: ID }))
  const events = page.getByRole('tab', { name: 'EVENTS' })
  await expect(events).toBeDisabled()
  await expect(events).toHaveAttribute('title', 'Arrives with M1b')
  await expect(page.getByRole('tab', { name: 'SUMMARY' })).toBeEnabled()
})

const LONG_CONTENT_ANALYSES = [
  makeAnalysis({ id: ID, status: 'failed', filename: LONG_FILENAME, started_at: STARTED_AT, error: LONG_ERROR }),
  makeLongDetectedAnalysis(),
]

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`analysis page does not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    for (const analysis of LONG_CONTENT_ANALYSES) {
      await openAnalysis(page, analysis)
      await expectHeaderShowing(page, analysis)
      await expectNoHorizontalOverflow(page)
    }
  })
}
