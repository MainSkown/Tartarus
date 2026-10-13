import type { Page } from '@playwright/test'
import type { NetworkView } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeDetectedAnalysis,
  mockAnalyses,
  mockShell,
  mockViews,
  realView,
  screenshotPath,
  test,
  waitForTransitions,
  type ViewMock,
} from './fixtures'

const ID = 45
const SUB_TABS = ['DNS', 'HTTP', 'TLS', 'FLOWS', 'ALERTS', 'HOSTS']
const LONG_DOMAIN = `${'subdomain-with-a-very-long-label.'.repeat(6)}example-malware-c2.net`
const LONG_URL = `http://${LONG_DOMAIN}/gate.php?id=${'0123456789abcdef'.repeat(24)}&session=${'x'.repeat(80)}`
const LONG_AGENT = `Mozilla/5.0 (Windows NT 10.0; Win64; x64) ${'AppleWebKit/537.36 (KHTML, like Gecko) '.repeat(6)}`
const EMPTY_LIST = { items: [], total: 0 }

async function openNetwork(
  page: Page,
  network: ViewMock = {},
  subTab?: string,
): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockViews(page, { network })
  await page.goto(`/analyses/${ID}/network`)
  if (network.status || network.delayMs) return
  await expect(page.getByRole('tab', { name: /^DNS/ })).toBeVisible()
  if (subTab) await page.getByRole('tab', { name: new RegExp(`^${subTab}`) }).click()
  await waitForTransitions(page)
}

function withView(changes: Partial<NetworkView>): ViewMock {
  return { body: { ...realView<NetworkView>('network'), ...changes } }
}

function longValues(): ViewMock {
  const real = realView<NetworkView>('network')
  const dns = real.dns.items[0]!
  const http = real.http.items[0]!
  const flow = real.flows.items[0]!
  return withView({
    dns: { items: [{ ...dns, query: LONG_DOMAIN, answers: Array.from({ length: 12 }, (_, i) => `10.0.0.${i + 1}`) }], total: 1 },
    http: { items: [{ ...http, url: LONG_URL, host: LONG_DOMAIN, user_agent: LONG_AGENT }], total: 1 },
    flows: { items: [{ ...flow, process: { pid: 4242, name: 'a_process_with_an_extremely_long_image_name_indeed.exe' } }], total: 1 },
    hosts: {
      items: [{ host: LONG_DOMAIN, kind: 'domain', count: 123456, related: Array.from({ length: 20 }, (_, i) => `related-host-${i}.example.org`) }],
      total: 1,
    },
  })
}

function manyFlows(): ViewMock {
  const real = realView<NetworkView>('network')
  const items = Array.from({ length: 200 }, (_, i) => ({ ...real.flows.items[i % real.flows.items.length]!, event_id: `flow-${i}` }))
  return withView({ flows: { items, total: 1437 } })
}

for (const name of SUB_TABS) {
  test(`network-${name.toLowerCase()}`, async ({ page }) => {
    await openNetwork(page, {}, name)
    await expect(page.getByRole('tab', { name: new RegExp(`^${name}`) })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('link', { name: /PCAP/ })).toHaveAttribute('href', `/api/analyses/${ID}/pcap`)
    await page.screenshot({ path: screenshotPath(`network-${name.toLowerCase()}`), fullPage: true })
  })
}

test('network-loading', async ({ page }) => {
  await openNetwork(page, { delayMs: 3000 })
  await expect(page.locator('.loader')).toBeVisible()
  await page.screenshot({ path: screenshotPath('network-loading') })
})

test('network-empty', async ({ page }) => {
  const empty = { dns: EMPTY_LIST, http: EMPTY_LIST, tls: EMPTY_LIST, flows: EMPTY_LIST, alerts: EMPTY_LIST, hosts: EMPTY_LIST }
  await openNetwork(page, withView(empty))
  await expect(page.getByText('no DNS queries recorded')).toBeVisible()
  await page.screenshot({ path: screenshotPath('network-empty') })
})

test('network-error', async ({ page }) => {
  await openNetwork(page, { status: 500, body: errorEnvelope('internal_error', 'OpenSearch is unreachable') })
  await expect(page.getByText('failed to load: OpenSearch is unreachable')).toBeVisible()
  await page.screenshot({ path: screenshotPath('network-error') })
})

test('network-not-simulated', async ({ page }) => {
  await openNetwork(page, withView({ simulated: false }), 'HTTP')
  await expect(page.locator('.network-table__inetsim')).toHaveCount(0)
  await page.screenshot({ path: screenshotPath('network-not-simulated'), fullPage: true })
})

test('network-empty-with-source-note', async ({ page }) => {
  await openNetwork(page, {}, 'TLS')
  await expect(page.getByText('TLS and Suricata alerts arrive with a later milestone')).toBeVisible()
  await page.screenshot({ path: screenshotPath('network-tls-empty') })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  for (const name of ['DNS', 'HTTP', 'FLOWS', 'HOSTS']) {
    test(`network-long-values-${name.toLowerCase()}-${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 })
      await openNetwork(page, longValues(), name)
      await expectNoHorizontalOverflow(page)
      await page.screenshot({ path: screenshotPath(`network-long-values-${name.toLowerCase()}-${width}`), fullPage: true })
    })
  }
}

test('network-flows-listed-of-total', async ({ page }) => {
  await openNetwork(page, manyFlows(), 'FLOWS')
  await expect(page.locator('.network-table__count')).toHaveText('listed 200 of 1437')
  await page.screenshot({ path: screenshotPath('network-flows-listed-of-total') })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`network-no-overflow-${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openNetwork(page, {}, 'HTTP')
    await expectNoHorizontalOverflow(page)
    if (width === 600) await page.screenshot({ path: screenshotPath('network-narrow-600'), fullPage: true })
  })
}
