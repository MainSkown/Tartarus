import type { Page } from '@playwright/test'
import type { AnalysisRead, Annotations, ErrorEnvelope, JobProgress, JobRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  expect,
  makeDetectedAnalysis,
  mockAnalyses,
  mockAnnotations,
  mockEvents,
  mockHealthGet,
  mockQuery,
  mockViews,
  screenshotPath,
  waitForTransitions,
} from './fixtures'

export const ANALYSIS_ID = 193
export const JOB_ID = 7
export const FINISHED_ANALYSIS = makeDetectedAnalysis({ id: ANALYSIS_ID, filename: 'invoice_scan.exe' })

type Reply = { status: number; body: ErrorEnvelope; delayMs?: number }

export interface ExportsMockOptions {
  /** What POST /export/report answers instead of the accepted job. */
  reportReply?: Reply
  /** What GET /export/iocs answers instead of the file. */
  iocReply?: Reply
  /** How long GET /export/iocs takes, so the "preparing" toast can be photographed. */
  iocDelayMs?: number
  /** The tags and notes the analysis opens with. */
  annotations?: Annotations
}

export interface ExportsMock {
  /** Resolves once the page's system socket is open. */
  connected(): Promise<void>
  /** One `job` message to the page, as `/ws/system` pushes it. */
  pushJob(job: Partial<JobProgress>): void
  reportRequests(): { format: string; include: Record<string, boolean> }[]
  iocRequests(): string[]
  /** The id of the job the next POST will answer with, for a retry. */
  nextJobId(id: number): void
}

const IOC_FILES: Record<string, { type: string; extension: string }> = {
  stix: { type: 'application/json', extension: 'stix.json' },
  misp: { type: 'application/json', extension: 'misp.json' },
  csv: { type: 'text/csv', extension: 'csv' },
}

export function reportJob(overrides: Partial<JobProgress> = {}): JobProgress {
  return {
    id: JOB_ID,
    type: 'export_report',
    analysis_id: ANALYSIS_ID,
    status: 'running',
    step: 'Reading the analysis files',
    progress: 0,
    result: null,
    ...overrides,
  }
}

export const DONE_PDF = reportJob({
  status: 'done',
  step: 'Saving the file',
  progress: 100,
  result: { file: `${ANALYSIS_ID}/tartarus-report-${ANALYSIS_ID}.pdf`, filename: `tartarus-report-${ANALYSIS_ID}.pdf`, media_type: 'application/pdf' },
})

function readOf(job: JobProgress): JobRead {
  return { ...job, log: '', created_at: '2026-10-15T10:00:00Z', updated_at: '2026-10-15T10:00:00Z' }
}

async function pause(ms: number | undefined): Promise<void> {
  if (ms) await new Promise((resolve) => setTimeout(resolve, ms))
}

/** Stands in for the system socket (health plus a way to push jobs), the export endpoints and the job file download. */
export async function mockExports(page: Page, options: ExportsMockOptions = {}): Promise<ExportsMock> {
  const sockets: { send(message: string): void }[] = []
  const reports: { format: string; include: Record<string, boolean> }[] = []
  const iocs: string[] = []
  let acceptedId = JOB_ID

  await mockHealthGet(page, GUEST_READY_SYSTEM)
  await page.routeWebSocket((url) => url.pathname === '/ws/system', (ws) => {
    sockets.push(ws)
    ws.send(JSON.stringify({ type: 'health', ts: new Date().toISOString(), data: GUEST_READY_SYSTEM }))
  })

  await page.route(
    (url) => /^\/api\/analyses\/\d+\/export\/report$/.test(url.pathname),
    async (route) => {
      reports.push(route.request().postDataJSON())
      if (options.reportReply) {
        await pause(options.reportReply.delayMs)
        await route.fulfill({ status: options.reportReply.status, json: options.reportReply.body })
        return
      }
      await route.fulfill({ status: 202, json: readOf(reportJob({ id: acceptedId, status: 'pending', step: 'Queued' })) })
    },
  )

  await page.route(
    (url) => /^\/api\/analyses\/\d+\/export\/iocs$/.test(url.pathname),
    async (route) => {
      const format = new URL(route.request().url()).searchParams.get('format') ?? ''
      iocs.push(format)
      await pause(options.iocDelayMs)
      if (options.iocReply) {
        await route.fulfill({ status: options.iocReply.status, json: options.iocReply.body })
        return
      }
      const file = IOC_FILES[format]!
      await route.fulfill({
        status: 200,
        contentType: file.type,
        headers: { 'Content-Disposition': `attachment; filename="tartarus-${ANALYSIS_ID}-iocs.${file.extension}"` },
        body: format === 'csv' ? 'type,value\nip,203.0.113.7\n' : '{"type":"bundle"}',
      })
    },
  )

  await page.route(
    (url) => /^\/api\/jobs\/\d+$/.test(url.pathname),
    async (route) => route.fulfill({ json: readOf(reportJob({ id: acceptedId, status: 'running', progress: 50, step: 'Rendering the PDF' })) }),
  )

  await page.route(
    (url) => /^\/api\/jobs\/\d+\/download$/.test(url.pathname),
    async (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        headers: { 'Content-Disposition': `attachment; filename="tartarus-report-${ANALYSIS_ID}.pdf"` },
        body: '%PDF-1.7 fake',
      }),
  )

  return {
    async connected() {
      await expect.poll(() => sockets.length, { message: 'waiting for the system socket' }).toBeGreaterThan(0)
    },
    pushJob(job) {
      const message = JSON.stringify({ type: 'job', job: reportJob(job) })
      for (const socket of sockets) socket.send(message)
    },
    reportRequests: () => reports,
    iocRequests: () => iocs,
    nextJobId(id) {
      acceptedId = id
    },
  }
}

export async function openAnalysis(page: Page, analysis: AnalysisRead = FINISHED_ANALYSIS, options: ExportsMockOptions = {}): Promise<ExportsMock> {
  const exports = await mockExports(page, options)
  await mockAnalyses(page, { items: [analysis] })
  await mockViews(page)
  await mockQuery(page)
  await mockEvents(page)
  if (options.annotations) await mockAnnotations(page, { annotations: options.annotations })
  await page.goto(`/analyses/${analysis.id}/summary`)
  await expect(page.locator('.analysis-header')).toBeVisible()
  await exports.connected()
  return exports
}

export async function openDashboard(page: Page, items: AnalysisRead[], options: ExportsMockOptions = {}): Promise<ExportsMock> {
  const exports = await mockExports(page, options)
  await mockAnalyses(page, { items })
  await page.goto('/')
  await expect(page.locator('.analysis-row').first()).toBeVisible()
  await exports.connected()
  return exports
}

const nextFrames = (page: Page): Promise<void> =>
  page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))

export async function snapshot(page: Page, name: string, { fullPage = true, toast = false } = {}): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  // Icons are a webfont: a picture taken before it loaded shows empty boxes where they go.
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  // A toast's timer bar is a finite animation that ends with the toast, so waiting it out would photograph an empty corner.
  if (toast) {
    await page.waitForFunction(() => document.querySelector('.q-notification[class*="-enter-"]') === null)
    await nextFrames(page)
  } else await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`export/${name}`), fullPage })
}
