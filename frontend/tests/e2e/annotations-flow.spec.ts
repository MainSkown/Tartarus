import { readFile } from 'node:fs/promises'
import { expect, test, type APIRequestContext, type Download, type Page } from '@playwright/test'

const ANALYSIS_ID = process.env.E2E_ANALYSIS_ID
const TEST_TIMEOUT_MS = 100_000
const REPORT_TIMEOUT_MS = 60_000

interface TagLink {
  link_id: number
  tag: string
  target_type: string
}
interface Annotations {
  tags: TagLink[]
  notes: { id: number; target_type: string; body: string }[]
}

const openTab = (page: Page, label: string) => page.getByRole('tab', { name: label, exact: true }).click()
const analysisUrl = (id: string) => `/api/analyses/${id}`

async function annotationsOf(request: APIRequestContext, id: string): Promise<Annotations> {
  const response = await request.get(`${analysisUrl(id)}/annotations`)
  expect(response.ok(), `GET annotations answered ${response.status()}`).toBe(true)
  return response.json()
}

/** A process the analysis ran: the tag the test seeds sits on it, so it is in use but not on the analysis itself. */
async function aProcessPid(request: APIRequestContext, id: string): Promise<number> {
  const response = await request.get(`${analysisUrl(id)}/processes`)
  expect(response.ok(), `GET processes answered ${response.status()}`).toBe(true)
  return (await response.json()).roots[0].pid
}

async function downloadedBy(page: Page, click: () => Promise<void>): Promise<{ download: Download; text: string }> {
  const waiting = page.waitForEvent('download')
  await click()
  const download = await waiting
  const path = await download.path()
  return { download, text: await readFile(path, 'utf8') }
}

async function openExportMenu(page: Page): Promise<void> {
  await page.getByRole('button', { name: '[EXPORT]' }).click()
  await expect(page.locator('.export-entries')).toBeVisible()
}

async function addSuggestedTag(page: Page, request: APIRequestContext, id: string, seed: string): Promise<void> {
  await page.getByRole('button', { name: 'Add tag' }).click()
  await page.getByRole('combobox', { name: 'New tag' }).fill(seed.slice(0, -3))
  const suggestion = page.getByRole('option').filter({ hasText: seed })
  await expect(suggestion, 'the autocomplete must offer the tag that is in use on a process').toBeVisible()
  await expect(suggestion.locator('.tag-input__option-count')).toHaveText(/^\d+$/)
  await suggestion.click()
  await expect(page.locator('.analysis-header .tag-chip', { hasText: seed })).toBeVisible()
  const { tags } = await annotationsOf(request, id)
  expect(
    tags.filter((link) => link.tag === seed && link.target_type === 'analysis'),
    'the chosen tag must be stored on the analysis',
  ).toHaveLength(1)
}

async function saveAnalysisNote(page: Page, request: APIRequestContext, id: string, text: string): Promise<void> {
  await openTab(page, 'NOTES')
  const field = page.locator('.notes-tab .note-editor textarea').first()
  await field.fill(text)
  await field.blur()
  await expect(page.locator('.q-notification', { hasText: 'Note saved' })).toBeVisible()
  const { notes } = await annotationsOf(request, id)
  expect(
    notes.filter((note) => note.target_type === 'analysis').map((note) => note.body),
    'the note must be stored on the analysis',
  ).toContain(text)
}

async function downloadStixIocs(page: Page, id: string): Promise<void> {
  await openExportMenu(page)
  const { download, text } = await downloadedBy(page, () => page.locator('.export-entries .q-item', { hasText: /^STIX 2\.1$/ }).click())
  expect(download.suggestedFilename()).toBe(`tartarus-${id}-iocs.stix.json`)
  expect(JSON.parse(text).type, 'the downloaded file must be a STIX bundle').toBe('bundle')
}

async function downloadHtmlReport(page: Page, id: string, noteText: string): Promise<void> {
  await openExportMenu(page)
  await page.locator('.export-entries .q-item', { hasText: /^HTML$/ }).click()
  await expect(page.locator('.report-dialog')).toBeVisible()
  await page.getByRole('button', { name: '[GENERATE]' }).click()
  const downloadButton = page.getByRole('button', { name: '[DOWNLOAD HTML]' })
  await expect(downloadButton, 'the report job must finish').toBeVisible({ timeout: REPORT_TIMEOUT_MS })
  const { download, text } = await downloadedBy(page, () => downloadButton.click())
  expect(download.suggestedFilename()).toBe(`tartarus-report-${id}.html`)
  expect(text, "the report must hold the note saved a moment ago").toContain(noteText)
  await page.getByRole('button', { name: 'CLOSE', exact: true }).click()
  await expect(page.locator('.report-dialog')).toBeHidden()
}

async function filterDashboardByTag(page: Page, id: string, tag: string): Promise<void> {
  await page.goto('/')
  await expect(page.locator('.analysis-row').first()).toBeVisible()
  await page.locator('.tag-select').click()
  await page.getByRole('option', { name: new RegExp(`^${tag} \\(\\d+\\)$`) }).click()
  const rows = page.locator('.analysis-row')
  await expect(rows, 'only the analysis carrying the tag on itself is listed').toHaveCount(1)
  await expect(rows.first().locator('.col-id')).toHaveText(id)
}

/** What the test added, taken back so a run on an analysis that is kept leaves it as it was. */
async function removeWhatTheTestAdded(request: APIRequestContext, id: string, tagPrefix: string, hadNote: boolean): Promise<void> {
  const { tags, notes } = await annotationsOf(request, id)
  for (const link of tags.filter((candidate) => candidate.tag.startsWith(tagPrefix))) {
    await request.delete(`${analysisUrl(id)}/tags/${link.link_id}`)
  }
  if (hadNote) return
  for (const note of notes.filter((candidate) => candidate.target_type === 'analysis')) await request.delete(`/api/notes/${note.id}`)
}

// Real stack, no mocks, on an analysis that is already done (scripts/e2e.sh passes the one it checks
// through the API): the analyst's flow in the browser, each step compared with what the API holds.
test('tag, note, export and report an analysis, then find it by its tag', async ({ page, request }) => {
  test.skip(!ANALYSIS_ID, 'E2E_ANALYSIS_ID must name a finished analysis; scripts/e2e.sh sets it')
  test.setTimeout(TEST_TIMEOUT_MS)
  const id = ANALYSIS_ID as string
  const seed = `e2e-${id}-ui-seed`
  const noteText = `browser verdict on analysis ${id}: nothing to see here`
  const hadNote = (await annotationsOf(request, id)).notes.some((note) => note.target_type === 'analysis')

  try {
    const seeded = await request.post(`${analysisUrl(id)}/tags`, {
      data: { tag: seed, target_type: 'process', target_ref: String(await aProcessPid(request, id)) },
    })
    expect(seeded.status(), 'seeding a tag on a process').toBe(201)

    await page.goto(`/analyses/${id}`)
    await expect(page.locator('.status-badge').first()).toContainText(/done/i)

    await test.step('a tag from the autocomplete goes on the analysis', () => addSuggestedTag(page, request, id, seed))
    await test.step('the analysis note is saved on blur with a toast', () => saveAnalysisNote(page, request, id, noteText))
    await test.step('the Export menu downloads the STIX IOCs', () => downloadStixIocs(page, id))
    await test.step('the report dialog builds and downloads the HTML report', () => downloadHtmlReport(page, id, noteText))
    await test.step('the Dashboard filters by the tag', () => filterDashboardByTag(page, id, seed))
  } finally {
    await removeWhatTheTestAdded(request, id, `e2e-${id}-ui-`, hadNote)
  }
})
