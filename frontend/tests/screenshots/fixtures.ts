import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { test as base, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { ErrorEnvelope, SettingsBody, SystemHealth } from '../../src/api/types.gen'

// An /api request no scenario mocked would fall through to the dev server's proxy (no backend
// behind it) and paint an error toast into the screenshot, so a mock whose URL drifted from
// what the app really requests (as a doubled /api/api prefix once did) produced a wrong picture
// without failing. This route is registered before each test's own mocks, and Playwright tries
// the most recently registered route first, so it only ever sees requests nothing else claimed.
// Matched on pathname, not a glob: Vite serves the app's own modules under /src/api/.
export const test = base.extend({
  page: async ({ page }, use) => {
    const unmocked: string[] = []
    await page.route(
      (url) => url.pathname.startsWith('/api/'),
      async (route) => {
        unmocked.push(route.request().url())
        await route.abort()
      },
    )
    await use(page)
    expect(unmocked, 'requests to /api that no scenario mocked').toEqual([])
  },
})

export { expect }

const SCREENSHOTS_DIR = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..', 'screenshots')

export function screenshotPath(name: string): string {
  return path.join(SCREENSHOTS_DIR, `${name}.png`)
}

// Exact pathnames, not globs: '**/api/settings' would also match a doubled '/api/api/settings'
// and serve a request the real backend would 404.
function atPath(pathname: string): (url: URL) => boolean {
  return (url) => url.pathname === pathname
}

const HEALTH_URL = atPath('/api/system/health')
const SETTINGS_URL = atPath('/api/settings')
const WS_SYSTEM_URL = atPath('/ws/system')

// cape/guest have no backing service at all yet in this phase (no CAPE container, no guest
// VM orchestration — see MainLayout.vue's deferred-items comment), so "ok" for them is a state
// the app can never actually be in right now. Every shell fixture keeps them "down, not set up
// yet" and only varies postgres/opensearch, the two services this phase really has.
export const HEALTHY_SYSTEM: SystemHealth = {
  postgres: { status: 'ok', message: null },
  opensearch: { status: 'ok', message: null },
  cape: { status: 'down', message: 'not set up yet' },
  guest: { status: 'down', message: 'not set up yet' },
}

export const OPENSEARCH_DOWN_SYSTEM: SystemHealth = {
  ...HEALTHY_SYSTEM,
  opensearch: { status: 'down', message: 'connection refused' },
}

export async function mockHealthGet(page: Page, health: SystemHealth = HEALTHY_SYSTEM): Promise<void> {
  await page.route(HEALTH_URL, async (route) => {
    await route.fulfill({ json: health })
  })
}

/**
 * Mocks `/ws/system` at the WebSocket protocol level via `page.routeWebSocket` (Playwright
 * 1.48+). Not calling `connectToServer()` means Playwright fully mocks the socket rather than
 * forwarding to a real server, which is exactly what's wanted here: the dev server's own `/ws`
 * proxy target (`backend:8000`) does not exist in this harness's environment.
 */
export async function mockHealthWebSocket(
  page: Page,
  options: { health?: SystemHealth; closeImmediately?: boolean } = {},
): Promise<void> {
  const health = options.health ?? HEALTHY_SYSTEM
  await page.routeWebSocket(WS_SYSTEM_URL, (ws) => {
    if (options.closeImmediately) {
      void ws.close()
      return
    }
    ws.send(JSON.stringify({ type: 'health', ts: new Date().toISOString(), data: health }))
  })
}

/** The combination every route under MainLayout needs: a GET snapshot plus a live WS push. */
export async function mockShell(page: Page, health: SystemHealth = HEALTHY_SYSTEM): Promise<void> {
  await mockHealthGet(page, health)
  await mockHealthWebSocket(page, { health })
}

/**
 * Mocks `/ws/system` as a connection that opens, then is immediately closed by the far end —
 * reproducing what `ws.ts`'s `ReconnectingWebSocketClient` sees on a dropped connection, so it
 * lands in the `reconnecting` state the "Reconnecting…" bar renders for.
 */
export async function mockFlappingHealthWebSocket(page: Page): Promise<void> {
  await mockHealthWebSocket(page, { closeImmediately: true })
}

export async function mockSettings(
  page: Page,
  options: {
    getBody: SettingsBody
    getDelayMs?: number
    putResponse?: { status: number; body: SettingsBody | ErrorEnvelope }
  },
): Promise<void> {
  await page.route(SETTINGS_URL, async (route) => {
    const method = route.request().method()
    if (method === 'GET') {
      if (options.getDelayMs) await new Promise((resolve) => setTimeout(resolve, options.getDelayMs))
      await route.fulfill({ json: options.getBody })
      return
    }
    if (method === 'PUT' && options.putResponse) {
      await route.fulfill({ status: options.putResponse.status, json: options.putResponse.body })
      return
    }
    await route.fallback()
  })
}

export function validationErrorEnvelope(fields: { field: string; message: string }[]): ErrorEnvelope {
  return {
    error: {
      code: 'validation_error',
      message: 'Request validation failed',
      details: {
        fields: fields.map(({ field, message }) => ({ location: ['body', field], message, type: 'value_error' })),
      },
    },
  }
}

/**
 * Waits until Quasar has finished fading in every field's inline message. Playwright's
 * `toBeVisible()` counts an element at opacity 0 as visible, so without this a screenshot can
 * land mid-transition and show the field's error border with its message still invisible.
 */
export async function waitForFieldMessages(page: Page): Promise<void> {
  await page.waitForFunction(() =>
    [...document.querySelectorAll('.q-field__bottom')].every(
      (bottom) => bottom.getAnimations({ subtree: true }).length === 0,
    ),
  )
}
