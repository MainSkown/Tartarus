import type { Page } from '@playwright/test'
import type { Annotations } from '../../src/api/types.gen'
import {
  ALERT_EVENT,
  ANALYSIS_ID,
  LONG_TAG,
  NETWORK_EVENT,
  USAGE,
  analysisAnnotations,
  note,
  populatedAnnotations,
  tag,
  twentyThousandCharacters,
} from './annotations-data'
import {
  GUEST_READY_SYSTEM,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeAnalysis,
  makeDetectedAnalysis,
  mockAnalyses,
  mockAnnotations,
  mockEvents,
  mockQuery,
  mockShell,
  mockViews,
  screenshotPath,
  test,
  waitForTransitions,
  type AnnotationsMockOptions,
} from './fixtures'

const HOLD_MS = 120_000
const NOTES_PATH = `/analyses/${ANALYSIS_ID}/notes`
const SERVER_ERROR = { status: 500, body: errorEnvelope('internal_error', 'The annotations store is unavailable') }
const POPULATED = populatedAnnotations([ALERT_EVENT, NETWORK_EVENT])

async function openNotes(
  page: Page,
  annotations: Annotations = POPULATED,
  options: AnnotationsMockOptions = {},
  analysis = makeDetectedAnalysis({ id: ANALYSIS_ID }),
): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockViews(page)
  await mockQuery(page)
  await mockEvents(page)
  await mockAnnotations(page, { annotations, usage: USAGE, ...options })
  await page.goto(NOTES_PATH)
  await expect(page.locator('[data-tab="notes"]')).toBeVisible()
}

async function snapshot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  // Icons are a webfont: a picture taken before it loaded shows empty boxes where they go.
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`notes/${name}`), fullPage: true })
}

async function listed(page: Page): Promise<void> {
  await expect(page.locator('.notes-entry').first()).toBeVisible()
  await expect(page.locator('.notes-entry__link').first()).toBeVisible()
}

test('notes-populated-all-targets-with-orphans', async ({ page }) => {
  await openNotes(page)
  await listed(page)
  await expect(page.locator('.notes-entry.is-orphaned')).toHaveCount(2)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, '01-populated-with-orphaned')
})

test('notes-empty', async ({ page }) => {
  await openNotes(page, analysisAnnotations())
  await expect(page.getByText('no tags or notes yet')).toBeVisible()
  await snapshot(page, '02-empty')
})

test('notes-loading', async ({ page }) => {
  await openNotes(page, POPULATED, { readDelayMs: HOLD_MS })
  await expect(page.locator('.notes-tab .loader')).toBeVisible()
  await snapshot(page, '03-loading')
})

test('notes-load-error', async ({ page }) => {
  await openNotes(page, POPULATED, { readError: SERVER_ERROR })
  await expect(page.getByText('failed to load: The annotations store is unavailable')).toBeVisible()
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await snapshot(page, '04-load-error')
})

test('notes-analysis-note-saving', async ({ page }) => {
  await openNotes(page, POPULATED, { noteWriteDelayMs: HOLD_MS })
  const field = page.locator('.notes-tab .note-editor textarea').first()
  await field.fill('Invoice lure from a spoofed supplier address. Second paragraph added after the memory dump.')
  await field.blur()
  await expect(page.locator('.note-editor__status')).toHaveText('SAVING…')
  await snapshot(page, '05-analysis-note-saving')
})

test('notes-analysis-note-save-error', async ({ page }) => {
  await openNotes(page, POPULATED, { noteWriteError: SERVER_ERROR })
  const field = page.locator('.notes-tab .note-editor textarea').first()
  await field.fill('Changed text that cannot be saved.')
  await field.blur()
  await expect(page.locator('.note-editor__status')).toHaveText('NOT SAVED')
  await expect(page.locator('.tt-toast--error')).toBeVisible()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await page.mouse.move(0, 0)
  await page.screenshot({ path: screenshotPath('notes/06-analysis-note-save-error'), fullPage: true })
})

test('notes-analysis-note-saved-toast', async ({ page }) => {
  await openNotes(page, analysisAnnotations())
  const field = page.locator('.notes-tab .note-editor textarea').first()
  await field.fill('First impression: a dropper delivered by an invoice lure.')
  await field.blur()
  await expect(page.locator('.tt-toast--success')).toBeVisible()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await page.mouse.move(0, 0)
  await page.screenshot({ path: screenshotPath('notes/07-analysis-note-saved-toast'), fullPage: true })
})

test('notes-running-analysis', async ({ page }) => {
  const running = makeAnalysis({ id: ANALYSIS_ID, status: 'running', started_at: '2026-10-12T09:14:30Z', tags: ['phishing'] })
  const during = analysisAnnotations({
    tags: [tag('phishing'), tag('dropper', 'process', '9708')],
    notes: [note('Taking notes while it detonates.')],
  })
  await openNotes(page, during, {}, running)
  await expect(page.locator('.notes-entry__link')).toHaveCount(1)
  await snapshot(page, '08-while-the-analysis-runs')
})

test('notes-long-tags-many-tags-and-20000-character-notes', async ({ page }) => {
  const heavy = analysisAnnotations({
    tags: [LONG_TAG, 'phishing', 'emotet', 'tlp:amber', 'dropper', 'needs-review', 'clean-baseline', ...'abcdefghijklmnopqrstuvwxyz'.split('')].flatMap((name) => [
      tag(name),
      tag(name, 'process', '9708'),
    ]),
    notes: [
      note(twentyThousandCharacters()),
      note(twentyThousandCharacters(), 'process', '9708'),
      note(twentyThousandCharacters(), 'event', ALERT_EVENT),
    ],
  })
  await openNotes(page, heavy)
  await listed(page)
  await expect(page.locator('.note-editor__counter')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await snapshot(page, '09-long-tags-many-tags-20000-char-notes')
})

test('notes-narrow-800', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 })
  await openNotes(page)
  await listed(page)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, '10-narrow-800')
})

test('notes-narrow-500-long-names', async ({ page }) => {
  await page.setViewportSize({ width: 500, height: 900 })
  await openNotes(page, analysisAnnotations({
    tags: [tag(LONG_TAG), tag(LONG_TAG, 'process', '9708'), tag(LONG_TAG, 'event', ALERT_EVENT)],
    notes: [note('A short note on the analysis.'), note('x'.repeat(300), 'event', ALERT_EVENT)],
  }))
  await listed(page)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, '11-narrow-500-long-names')
})

test('notes-process-link-opens-the-process', async ({ page }) => {
  await openNotes(page)
  await page.locator('.notes-entry__link', { hasText: '(9708)' }).click()
  await expect(page).toHaveURL(/\/analyses\/45\/processes\?sel=9708/)
  await expect(page.locator('.process-details__title')).toContainText('(9708)')
})

test('notes-event-link-opens-the-event-drawer', async ({ page }) => {
  await openNotes(page)
  await page.locator('.notes-entry__link', { hasText: `event ${ALERT_EVENT.slice(0, 8)}` }).click()
  await expect(page).toHaveURL(new RegExp(`/analyses/45/events\\?e=${ALERT_EVENT}`))
  await expect(page.locator('.event-detail__title')).toBeVisible()
})
