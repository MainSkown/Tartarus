import type { Page } from '@playwright/test'
import type { Annotations, AnalysisRead } from '../../src/api/types.gen'
import {
  ALERT_EVENT,
  ANALYSIS_ID,
  LONG_TAG,
  TAGGED_ANALYSES,
  USAGE,
  analysisAnnotations,
  note,
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
const SERVER_ERROR = { status: 500, body: errorEnvelope('internal_error', 'The annotations store is unavailable') }

function analysisTags(annotations: Annotations): string[] {
  return annotations.tags.filter((link) => link.target_type === 'analysis').map((link) => link.tag)
}

async function openDashboard(page: Page, options: AnnotationsMockOptions = {}, items = TAGGED_ANALYSES): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items })
  await mockAnnotations(page, { usage: USAGE, ...options })
  await page.goto('/')
  await expect(page.locator('.analysis-row').first()).toBeVisible()
}

async function openWorkspace(
  page: Page,
  path: string,
  annotations: Annotations = analysisAnnotations(),
  options: AnnotationsMockOptions = {},
  analysis?: AnalysisRead,
): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis ?? makeDetectedAnalysis({ id: ANALYSIS_ID, tags: analysisTags(annotations) })] })
  await mockViews(page)
  await mockQuery(page)
  await mockEvents(page)
  await mockAnnotations(page, { annotations, usage: USAGE, ...options })
  await page.goto(path)
}

async function snapshot(page: Page, name: string, { fullPage = true } = {}): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  // Icons are a webfont: a picture taken before it loaded shows empty boxes where they go.
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`tags/${name}`), fullPage })
}

const SUMMARY = `/analyses/${ANALYSIS_ID}/summary`
const eventPath = (id: string): string => `/analyses/${ANALYSIS_ID}/events?e=${id}`
const newTagField = (page: Page) => page.getByRole('combobox', { name: 'New tag' })

const HEADER_ANNOTATIONS = analysisAnnotations({ tags: [tag('phishing'), tag('emotet'), tag('tlp:amber')] })

async function openAddTag(page: Page, scope = page.locator('.analysis-header')): Promise<void> {
  await scope.getByRole('button', { name: 'Add tag' }).click()
  await expect(newTagField(page)).toBeFocused()
}

// ---------- Dashboard ----------

test('tags-dashboard-tags-column', async ({ page }) => {
  await openDashboard(page)
  await expect(page.locator('.tag-list__more').first()).toHaveText('+2')
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'dashboard-01-tags-column')
})

test('tags-dashboard-tag-filter-open', async ({ page }) => {
  await openDashboard(page)
  await page.locator('.tag-select').click()
  await expect(page.getByRole('option', { name: 'phishing (7)' })).toBeVisible()
  await snapshot(page, 'dashboard-02-tag-filter-open')
})

test('tags-dashboard-tag-filter-active', async ({ page }) => {
  await openDashboard(page)
  await page.locator('.tag-select').click()
  await page.getByRole('option', { name: 'phishing (7)' }).click()
  await expect(page.locator('.analysis-row')).toHaveCount(2)
  await snapshot(page, 'dashboard-03-tag-filter-active')
})

test('tags-dashboard-tag-filter-no-match', async ({ page }) => {
  await openDashboard(page)
  await page.locator('.tag-select').click()
  await page.getByRole('option', { name: 'dropper (2)' }).click()
  await page.locator('.status-select').click()
  await page.getByRole('option', { name: 'FAILED', exact: true }).click()
  await expect(page.getByText('no analyses match')).toBeVisible()
  await snapshot(page, 'dashboard-04-tag-filter-no-match')
})

test('tags-dashboard-narrow-800', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 })
  await openDashboard(page)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'dashboard-05-narrow-800', { fullPage: false })
  await page.locator('.tt-table-scroll').evaluate((table) => table.scrollTo({ left: table.scrollWidth }))
  await snapshot(page, 'dashboard-05b-narrow-800-table-scrolled-to-tags', { fullPage: false })
})

test('tags-dashboard-many-and-long-tags', async ({ page }) => {
  const crowded = TAGGED_ANALYSES.map((analysis) =>
    analysis.id === 6
      ? { ...analysis, tags: [LONG_TAG, 'phishing', 'emotet', 'tlp:amber', 'dropper', 'needs-review', 'a', 'b', 'c', 'd', 'e', 'f'] }
      : analysis,
  )
  await openDashboard(page, {}, crowded)
  await expect(page.locator('.tag-list__more').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'dashboard-06-many-and-long-tags')
})

// ---------- Analysis header ----------

test('tags-header-with-tags', async ({ page }) => {
  await openWorkspace(page, SUMMARY, HEADER_ANNOTATIONS)
  await expect(page.locator('.analysis-header .tag-chip')).toHaveCount(3)
  await snapshot(page, 'header-01-with-tags')
})

test('tags-header-without-tags', async ({ page }) => {
  await openWorkspace(page, SUMMARY)
  await expect(page.getByRole('button', { name: 'Add tag' })).toBeVisible()
  await snapshot(page, 'header-02-no-tags')
})

test('tags-header-add-tag-autocomplete-open', async ({ page }) => {
  await openWorkspace(page, SUMMARY, HEADER_ANNOTATIONS)
  await openAddTag(page)
  await newTagField(page).fill('e')
  await expect(page.locator('.tag-input__option').first()).toBeVisible()
  await snapshot(page, 'header-03-add-tag-autocomplete-open')
})

test('tags-header-add-tag-validation-error', async ({ page }) => {
  await openWorkspace(page, SUMMARY, HEADER_ANNOTATIONS)
  await openAddTag(page)
  await newTagField(page).fill('Bad Tag!')
  await expect(page.locator('.tag-input__message')).toHaveText("only a-z, 0-9, '.', '_' and '-'")
  await snapshot(page, 'header-04-add-tag-validation-error')
})

test('tags-header-add-tag-duplicate', async ({ page }) => {
  await openWorkspace(page, SUMMARY, HEADER_ANNOTATIONS)
  await openAddTag(page)
  await newTagField(page).fill('phishing')
  await expect(page.locator('.tag-input__message')).toHaveText('already on this target')
  await snapshot(page, 'header-05-add-tag-duplicate')
})

test('tags-header-add-tag-server-refused', async ({ page }) => {
  await openWorkspace(page, SUMMARY, HEADER_ANNOTATIONS, {
    addTagError: { status: 409, body: errorEnvelope('conflict', 'Tag needs-review is already on this target') },
  })
  await openAddTag(page)
  await newTagField(page).fill('needs-review')
  await newTagField(page).press('Enter')
  await expect(page.locator('.tag-input__message')).toHaveText('Tag needs-review is already on this target')
  await snapshot(page, 'header-06-add-tag-server-refused')
})

test('tags-header-add-then-remove', async ({ page }) => {
  await openWorkspace(page, SUMMARY, HEADER_ANNOTATIONS)
  await openAddTag(page)
  await newTagField(page).fill('Needs-Review')
  await newTagField(page).press('Enter')
  await expect(page.locator('.analysis-header .tag-chip')).toHaveCount(4)
  await page.getByRole('button', { name: 'Remove tag emotet' }).click()
  await expect(page.locator('.analysis-header .tag-chip')).toHaveCount(3)
  await expect(page.locator('.analysis-header .tag-chip', { hasText: 'needs-review' })).toBeVisible()
})

test('tags-header-many-and-long-tags', async ({ page }) => {
  const many = analysisAnnotations({
    tags: [LONG_TAG, 'phishing', 'emotet', 'tlp:amber', 'dropper', 'needs-review', 'clean-baseline', ...'abcdefghijklmnop'.split('')].map((name) => tag(name)),
  })
  await openWorkspace(page, SUMMARY, many)
  await expect(page.locator('.analysis-header .tag-chip')).toHaveCount(23)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'header-07-many-and-long-tags')
})

test('tags-header-annotations-load-error', async ({ page }) => {
  await openWorkspace(page, SUMMARY, analysisAnnotations(), { readError: SERVER_ERROR })
  await expect(page.locator('.analysis-header')).toBeVisible()
  await snapshot(page, 'header-08-annotations-load-error')
})

test('tags-header-narrow-800', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 })
  await openWorkspace(page, SUMMARY, HEADER_ANNOTATIONS)
  await openAddTag(page)
  await newTagField(page).fill('e')
  await expect(page.locator('.tag-input__option').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'header-09-narrow-800-autocomplete')
})

// ---------- Event drawer ----------

const EVENT_ANNOTATIONS = analysisAnnotations({
  tags: [tag('c2', 'event', ALERT_EVENT), tag('needs-review', 'event', ALERT_EVENT)],
  notes: [note('Beacon every 30 seconds with jitter; matches the Emotet epoch 5 domain list.', 'event', ALERT_EVENT)],
})

async function openDrawer(page: Page, annotations: Annotations, options: AnnotationsMockOptions = {}): Promise<void> {
  await openWorkspace(page, eventPath(ALERT_EVENT), annotations, options)
  await expect(page.locator('.event-detail__title')).toBeVisible()
  // The drawer slides in; interacting or photographing before it stops catches it a few pixels off.
  await waitForTransitions(page)
}

const drawerNote = (page: Page) => page.locator('.event-detail .note-editor textarea')

test('tags-drawer-tags-and-note', async ({ page }) => {
  await openDrawer(page, EVENT_ANNOTATIONS)
  await expect(page.locator('.event-detail .tag-chip')).toHaveCount(2)
  await expect(drawerNote(page)).toHaveValue(/Beacon every 30 seconds/)
  await snapshot(page, 'drawer-01-tags-and-note', { fullPage: false })
})

test('tags-drawer-empty', async ({ page }) => {
  await openDrawer(page, analysisAnnotations())
  await expect(page.locator('.event-detail .tag-input__add')).toBeVisible()
  await snapshot(page, 'drawer-02-empty', { fullPage: false })
})

test('tags-drawer-add-tag-autocomplete', async ({ page }) => {
  await openDrawer(page, EVENT_ANNOTATIONS)
  await openAddTag(page, page.locator('.event-detail'))
  await newTagField(page).fill('d')
  await expect(page.locator('.tag-input__option').first()).toBeVisible()
  await snapshot(page, 'drawer-03-add-tag-autocomplete', { fullPage: false })
})

test('tags-drawer-note-saving', async ({ page }) => {
  await openDrawer(page, analysisAnnotations(), { noteWriteDelayMs: HOLD_MS })
  await drawerNote(page).fill('Check the injected thread against the memory dump.')
  await drawerNote(page).blur()
  await expect(page.locator('.note-editor__status')).toHaveText('SAVING…')
  await snapshot(page, 'drawer-04-note-saving', { fullPage: false })
})

test('tags-drawer-note-saved', async ({ page }) => {
  await openDrawer(page, analysisAnnotations())
  await drawerNote(page).fill('Check the injected thread against the memory dump.')
  await drawerNote(page).blur()
  await expect(page.locator('.note-editor__status')).toHaveText('SAVED')
  await expect(page.locator('.tt-toast--success')).toBeVisible()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await page.mouse.move(0, 0)
  await page.screenshot({ path: screenshotPath('tags/drawer-05-note-saved-toast') })
})

test('tags-drawer-note-save-error', async ({ page }) => {
  await openDrawer(page, analysisAnnotations(), { noteWriteError: SERVER_ERROR })
  await drawerNote(page).fill('Check the injected thread against the memory dump.')
  await drawerNote(page).blur()
  await expect(page.locator('.note-editor__status')).toHaveText('NOT SAVED')
  await expect(page.locator('.tt-toast--error')).toBeVisible()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await page.mouse.move(0, 0)
  await page.screenshot({ path: screenshotPath('tags/drawer-06-note-save-error-toast') })
})

test('tags-drawer-tag-refused-inline', async ({ page }) => {
  await openDrawer(page, EVENT_ANNOTATIONS, {
    addTagError: { status: 409, body: errorEnvelope('conflict', 'Analysis 45 is running: events can be annotated once the analysis is finished') },
  })
  await openAddTag(page, page.locator('.event-detail'))
  await newTagField(page).fill('lateral')
  await newTagField(page).press('Enter')
  await expect(page.locator('.tag-input__message')).toContainText('once the analysis is finished')
  await snapshot(page, 'drawer-07-tag-refused-inline', { fullPage: false })
})

test('tags-drawer-annotations-loading', async ({ page }) => {
  await openDrawer(page, analysisAnnotations(), { readDelayMs: HOLD_MS })
  await expect(page.locator('.target-annotations__skeleton')).toBeVisible()
  await snapshot(page, 'drawer-08-annotations-loading', { fullPage: false })
})

test('tags-drawer-annotations-error', async ({ page }) => {
  await openDrawer(page, analysisAnnotations(), { readError: SERVER_ERROR })
  await expect(page.locator('.event-detail .retry-btn')).toBeVisible()
  await snapshot(page, 'drawer-09-annotations-error', { fullPage: false })
})

test('tags-drawer-long-tag-many-tags-and-20000-character-note', async ({ page }) => {
  const heavy = analysisAnnotations({
    tags: [LONG_TAG, 'phishing', 'emotet', 'tlp:amber', 'dropper', 'needs-review', 'clean-baseline', 'x', 'y', 'z'].map((name) => tag(name, 'event', ALERT_EVENT)),
    notes: [note(twentyThousandCharacters(), 'event', ALERT_EVENT)],
  })
  await openDrawer(page, heavy)
  await expect(page.locator('.event-detail .tag-chip')).toHaveCount(10)
  await expect(page.locator('.note-editor__counter')).toBeVisible()
  const overflowing = await page.locator('.event-detail').evaluate((panel) => panel.scrollWidth > panel.clientWidth + 1)
  expect(overflowing, 'the drawer is wider than its box').toBe(false)
  await snapshot(page, 'drawer-10-long-tag-many-tags-20000-char-note', { fullPage: false })
})

// ---------- Process panel ----------

const PROCESS_ANNOTATIONS = analysisAnnotations({
  tags: [tag('dropper', 'process', '9708'), tag('injector', 'process', '9708')],
  notes: [note('Unpacks in memory, then spawns cmd.exe for host discovery.\nCheck the injected thread against the memory dump.', 'process', '9708')],
})

test('tags-process-panel-tags-and-note', async ({ page }) => {
  await openWorkspace(page, `/analyses/${ANALYSIS_ID}/processes`, PROCESS_ANNOTATIONS)
  await expect(page.locator('.process-details .tag-chip')).toHaveCount(2)
  await expect(page.locator('.process-details__apis')).toBeVisible()
  await snapshot(page, 'process-01-tags-and-note')
})

test('tags-process-panel-empty', async ({ page }) => {
  await openWorkspace(page, `/analyses/${ANALYSIS_ID}/processes`, analysisAnnotations())
  await expect(page.locator('.process-details .tag-input__add')).toBeVisible()
  await expect(page.locator('.process-details__apis')).toBeVisible()
  await snapshot(page, 'process-02-empty')
})

test('tags-process-panel-add-tag-autocomplete', async ({ page }) => {
  await openWorkspace(page, `/analyses/${ANALYSIS_ID}/processes`, PROCESS_ANNOTATIONS)
  await openAddTag(page, page.locator('.process-details'))
  await newTagField(page).fill('e')
  await expect(page.locator('.tag-input__option').first()).toBeVisible()
  await snapshot(page, 'process-03-add-tag-autocomplete')
})

test('tags-process-panel-note-error', async ({ page }) => {
  await openWorkspace(page, `/analyses/${ANALYSIS_ID}/processes`, analysisAnnotations(), { noteWriteError: SERVER_ERROR })
  const field = page.locator('.process-details .note-editor textarea')
  await field.fill('Spawns cmd.exe.')
  await field.blur()
  await expect(page.locator('.note-editor__status')).toHaveText('NOT SAVED')
  await expect(page.locator('.tt-toast--error')).toBeVisible()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await page.mouse.move(0, 0)
  await page.screenshot({ path: screenshotPath('tags/process-04-note-error-toast'), fullPage: true })
})

test('tags-process-panel-narrow-800', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 })
  await openWorkspace(page, `/analyses/${ANALYSIS_ID}/processes`, PROCESS_ANNOTATIONS)
  await expect(page.locator('.process-details .tag-chip')).toHaveCount(2)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'process-05-narrow-800')
})

// ---------- Event drawer while the analysis is not finished ----------

// The drawer lives in the Events and Timeline tabs, which only render for a finished analysis, so no
// click path reaches it on a running one. This mounts the real drawer (the page's own component, with
// its own app context, stores and mocks) over the Notes tab, which does work on a running analysis.
async function mountDrawerOverRunningAnalysis(page: Page, eventId: string): Promise<void> {
  await page.evaluate(async (id) => {
    const app = (document.querySelector('#q-app') as unknown as { __vue_app__: { _context: object; config: { globalProperties: { $pinia: object } } } }).__vue_app__
    const vueUrl = performance.getEntriesByType('resource').map((entry) => entry.name).find((name) => /\/deps\/vue\.js/.test(name))!
    const { h, render } = await import(/* @vite-ignore */ vueUrl)
    // Served by the dev server at these URLs, the same modules (and so the same stores) the page runs.
    const drawerUrl = '/src/components/EventDetailDrawer.vue'
    const queryStoreUrl = '/src/stores/query-state.ts'
    const { default: Drawer } = await import(/* @vite-ignore */ drawerUrl)
    const { useQueryStateStore } = await import(/* @vite-ignore */ queryStoreUrl)
    const container = document.createElement('div')
    document.body.appendChild(container)
    const vnode = h(Drawer)
    vnode.appContext = app._context
    render(vnode, container)
    useQueryStateStore(app.config.globalProperties.$pinia).openEvent(id)
  }, eventId)
}

test('tags-drawer-live-analysis-hint', async ({ page }) => {
  const running = makeAnalysis({ id: ANALYSIS_ID, status: 'running', started_at: '2026-10-12T09:14:30Z' })
  await openWorkspace(page, `/analyses/${ANALYSIS_ID}/notes`, analysisAnnotations(), {}, running)
  await expect(page.locator('[data-tab="notes"]')).toBeVisible()
  await mountDrawerOverRunningAnalysis(page, ALERT_EVENT)
  await expect(page.locator('.event-detail__title')).toBeVisible()
  await expect(page.locator('.target-annotations__hint')).toHaveText('events can be tagged and noted once the analysis is finished')
  await expect(page.locator('.event-detail .tag-input__add')).toHaveCount(0)
  await expect(page.locator('.event-detail textarea')).toHaveCount(0)
  await waitForTransitions(page)
  await snapshot(page, 'drawer-11-live-analysis-hint', { fullPage: false })
})
