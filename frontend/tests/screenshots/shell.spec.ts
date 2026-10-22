import {
  expect,
  HEALTHY_SYSTEM,
  OPENSEARCH_DOWN_SYSTEM,
  mockFlappingHealthWebSocket,
  mockAnalyses,
  mockHealthGet,
  mockQueueGet,
  mockShell,
  screenshotPath,
  test,
} from './fixtures'

// The Store dot's accessible name only includes "Postgres: ok · OpenSearch: ..." once the
// system store has applied a real health payload (see MainLayout.vue's storeSubStatuses) —
// before that it just reads "down" from the unloaded fallback. Waiting for the full text is
// therefore a wait for "the mocked health actually reached the page", not a fixed sleep.
function storeDotName(health: typeof HEALTHY_SYSTEM): string {
  const describe = (c: { status: string; message?: string | null }) =>
    c.message ? `${c.status} — ${c.message}` : c.status
  return `Store: Postgres: ${describe(health.postgres)} · OpenSearch: ${describe(health.opensearch)}`
}

test('shell-healthy', async ({ page }) => {
  await mockShell(page, HEALTHY_SYSTEM)
  await mockAnalyses(page, { items: [] })
  await page.goto('/')
  await expect(page.getByRole('status', { name: storeDotName(HEALTHY_SYSTEM), exact: true })).toBeVisible()
  await expect(page.getByRole('status', { name: 'CAPE: down — not set up yet', exact: true })).toBeVisible()
  await page.screenshot({ path: screenshotPath('shell-healthy') })
})

test('shell-opensearch-down', async ({ page }) => {
  await mockShell(page, OPENSEARCH_DOWN_SYSTEM)
  await mockAnalyses(page, { items: [] })
  await page.goto('/')
  await expect(page.getByRole('status', { name: storeDotName(OPENSEARCH_DOWN_SYSTEM), exact: true })).toBeVisible()
  await page.screenshot({ path: screenshotPath('shell-opensearch-down') })
})

test('shell-reconnecting', async ({ page }) => {
  await mockHealthGet(page, HEALTHY_SYSTEM)
  await mockQueueGet(page)
  await mockFlappingHealthWebSocket(page)
  await mockAnalyses(page, { items: [] })
  await page.goto('/')
  const reconnectBar = page.locator('.reconnect-bar')
  await expect(reconnectBar).toBeVisible()
  await expect(reconnectBar).toHaveText('Reconnecting…')
  await page.screenshot({ path: screenshotPath('shell-reconnecting') })
})

test('shell-narrow-1024', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 })
  await mockShell(page, HEALTHY_SYSTEM)
  await mockAnalyses(page, { items: [] })
  await page.goto('/')
  await expect(page.getByRole('status', { name: storeDotName(HEALTHY_SYSTEM), exact: true })).toBeVisible()
  await page.screenshot({ path: screenshotPath('shell-narrow-1024') })
})
