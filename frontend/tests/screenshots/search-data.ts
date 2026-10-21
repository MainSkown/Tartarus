import type { Page, Route } from '@playwright/test'
import type { CrossSearchEvent, CrossSearchResponse, ErrorEnvelope, Event, SearchRequest } from '../../src/api/types.gen'
import { errorEnvelope, sampleEvents } from './fixtures'

const SEARCH_URL = (url: URL): boolean => url.pathname === '/api/search'
const LONG_EXE = `${'a_remarkably_long_image_name_'.repeat(4)}.exe`
const LONG_PATH = `C:\\Users\\Analyst\\AppData\\Local\\Temp\\${'nested_folder_name\\'.repeat(6)}loader.exe`
const LONG_COMMAND = `"${LONG_PATH}" -WindowStyle Hidden -EncodedCommand ${'SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABOAGUAdAAuAFcAZQBiAEMAbABpAGUAbgB0ACkA'.repeat(3)}`

export const ANALYSES_WITH_HITS = [45, 46, 47] as const

/** A hit as the server labels it: the analysis it came from beside the event. */
export function hitOf(analysisId: number, event: Event): CrossSearchEvent {
  return { analysis_id: analysisId, event: { ...event, id: `${analysisId}-${event.id}` } }
}

/** A few real sample events spread over three analyses, plus one whose process path and command line are very long. */
export function severalAnalysesHits(): CrossSearchEvent[] {
  const samples = sampleEvents()
  const hits = samples.slice(0, 11).map((event, index) => hitOf(ANALYSES_WITH_HITS[index % ANALYSES_WITH_HITS.length]!, event))
  const longEvent: Event = {
    ...samples[11]!,
    summary: `${LONG_EXE} started ${LONG_COMMAND}`,
    process: { pid: 4312, name: LONG_EXE, entity_id: null },
  }
  return [...hits, hitOf(46, longEvent)]
}

/** All 250 sample events spread over three analyses: enough for two pages of the search. */
export function pagedHits(): CrossSearchEvent[] {
  return sampleEvents().map((event, index) => hitOf(ANALYSES_WITH_HITS[index % ANALYSES_WITH_HITS.length]!, event))
}

export interface SearchMockOptions {
  /** Every hit the search has, in the order the server returns them; each page is cut from this list. */
  hits?: CrossSearchEvent[]
  /** What the search says it matched; more than `hits` makes the result paged by the server. */
  total?: number
  /** Makes the search answer slowly, to catch the table in its loading state. */
  delayMs?: number
  /** Answers every search with this error instead of a page. */
  failure?: { status: number; body: ErrorEnvelope }
}

export interface SearchMock {
  requests: SearchRequest[]
}

function offsetOf(cursor: string | null | undefined): number {
  if (!cursor) return 0
  return Number(JSON.parse(Buffer.from(cursor, 'base64url').toString()).after)
}

function cursorAt(offset: number): string {
  return Buffer.from(JSON.stringify({ after: offset })).toString('base64url')
}

async function pause(ms: number | undefined): Promise<void> {
  if (ms) await new Promise((resolve) => setTimeout(resolve, ms))
}

/** Serves `POST /api/search` as the cross-analysis search: pages cut from `hits`, paged by an opaque cursor. */
export async function mockSearch(page: Page, options: SearchMockOptions = {}): Promise<SearchMock> {
  const mock: SearchMock = { requests: [] }
  const hits = options.hits ?? []
  await page.route(SEARCH_URL, async (route: Route) => {
    const body = route.request().postDataJSON() as SearchRequest
    mock.requests.push(body)
    await pause(options.delayMs)
    if (options.failure) return route.fulfill({ status: options.failure.status, json: options.failure.body })
    const offset = offsetOf(body.search_after)
    const next = offset + (body.size ?? 100)
    const reply: CrossSearchResponse = {
      events: hits.slice(offset, next),
      total: options.total ?? hits.length,
      next_cursor: next < hits.length ? cursorAt(next) : null,
    }
    await route.fulfill({ json: reply })
  })
  return mock
}

export const SEARCH_FAILURE = {
  status: 500,
  body: errorEnvelope('opensearch_unavailable', 'OpenSearch is not answering'),
}
