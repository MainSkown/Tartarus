import type { Page, Route } from '@playwright/test'
import type { BuildView, Guest } from '../../src/api/types.gen'
import { BUILD_LAB4, LAB5_FAILED, LONG_GUEST, LONG_NAME, mockGuestApi, type GuestApiMock } from './guest-page-data'
import { errorEnvelope } from './fixtures'

const UNBUILT_NAME = 'lab6'

/** A failed guest whose build never reached its self-test: no verdict, so no re-run control. */
export const UNBUILT_FAILED: Guest = {
  ...LAB5_FAILED,
  name: UNBUILT_NAME,
  error: 'build stopped: the guest did not answer within 15 minutes after the reboot',
  selftest: null,
  build_id: 'build-lab6',
  ip: null,
  badges: ['DEFENDER OFF'],
} as Guest

/** A failed guest with a self-test verdict and a name at the length the page must still fit. */
export const LONG_FAILED: Guest = {
  ...LONG_GUEST,
  state: 'failed',
  error: 'self-test failed: the sample did not write its registry key before the timeout',
}

export const LONG_REFUSAL =
  `${LONG_NAME} cannot run its self-test while an analysis is queued or running on the guest; the self-test reverts the snapshot, so it waits for the queue to empty, then try again ${'and again '.repeat(3)}`.trim()

const TESTING_BUILD_ID = 'build-lab5-retest'

export interface RetestMockOptions {
  guests: Guest[]
  /** The control service refuses the re-run with 409 and this message. */
  retestRefusal?: string
  /** Keeps the re-run request in flight until it is released, to photograph the busy button. */
  holdRetest?: Promise<void>
}

export interface RetestApiMock {
  api: GuestApiMock
  retestRequests: string[]
}

function selftestRequest(pathname: string): string | undefined {
  return /^\/api\/guests\/([^/]+)\/selftest$/.exec(pathname)?.[1]
}

function testingBuild(guest: string): BuildView {
  return {
    ...BUILD_LAB4,
    id: TESTING_BUILD_ID,
    guest,
    kind: 'selftest',
    status: 'running',
    percent: 80,
    message: 'Running the self-test: the benign sample is in the guest',
  } as BuildView
}

/**
 * Serves the Guest page as `mockGuestApi` does, plus the re-run endpoint. The re-run flips the guest to
 * TESTING in the list the next reload reads, as the control service does, so the card's reaction is real.
 * Registered after `mockGuestApi`, so Playwright tries it first and hands everything else back to it.
 */
export async function mockRetestApi(page: Page, options: RetestMockOptions): Promise<RetestApiMock> {
  const api: GuestApiMock = { guests: options.guests }
  const retestRequests: string[] = []
  let retestedName = ''
  await mockGuestApi(page, api)

  await page.route(
    (url) => selftestRequest(url.pathname) !== undefined,
    async (route: Route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      const name = selftestRequest(new URL(route.request().url()).pathname) ?? ''
      retestRequests.push(name)
      retestedName = name
      await options.holdRetest
      if (options.retestRefusal) {
        await route.fulfill({ status: 409, json: errorEnvelope('conflict', options.retestRefusal) })
        return
      }
      api.guests = api.guests.map((guest) =>
        guest.name === name ? { ...guest, state: 'testing', error: undefined, selftest: null, build_id: TESTING_BUILD_ID } : guest,
      )
      await route.fulfill({ status: 202, json: { job_id: 9, build_id: TESTING_BUILD_ID, guest: name } })
    },
  )

  await page.route(
    (url) => url.pathname === `/api/guests/builds/${TESTING_BUILD_ID}`,
    (route) => route.fulfill({ json: testingBuild(retestedName) }),
  )

  return { api, retestRequests }
}

