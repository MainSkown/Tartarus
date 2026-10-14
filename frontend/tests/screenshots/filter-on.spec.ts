import type { Locator, Page } from '@playwright/test'
import type { ArtifactsView, DetectionsView, NetworkView, RegistryView } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  expect,
  expectNoHorizontalOverflow,
  makeDetectedAnalysis,
  mockAnalyses,
  mockEvents,
  mockQuery,
  mockShell,
  mockViews,
  realView,
  sampleEvents,
  screenshotPath,
  test,
  waitForTransitions,
  type ViewMock,
  type ViewName,
} from './fixtures'

const ID = 45
const BENIGN = { pid: 9708, name: 'benign.exe' }
const CMD = { pid: 2476, name: 'cmd.exe' }
const VISIBLE_ROWS = '.artifact-panel:visible tbody tr'
const PANEL_ROWS = (page: Page): Locator => page.locator(VISIBLE_ROWS)
const NARROW = { width: 800, height: 720 }
const LONG_DOMAIN = `${'subdomain-with-a-very-long-label.'.repeat(5)}example-malware-c2.net`
const LONG_URL = `http://${LONG_DOMAIN}/gate.php?id=${'0123456789abcdef'.repeat(20)}`
const LONG_PATH = `C:\\Users\\Analyst\\AppData\\Local\\Temp\\${'nested_directory_'.repeat(8)}loader.exe`

type Views = Partial<Record<ViewName, ViewMock>>

async function open(page: Page, route: string, views: Views = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockQuery(page)
  await mockEvents(page)
  await mockViews(page, views)
  await page.goto(`/analyses/${ID}/${route}`)
}

async function capture(page: Page, name: string, fullPage = false): Promise<void> {
  // A click on a list entry far down the page scrolls it, which would cut the header off the picture.
  await page.evaluate(() => window.scrollTo(0, 0))
  await waitForTransitions(page)
  await page.mouse.move(0, 0)
  await page.screenshot({ path: screenshotPath(`filter-on/${name}`), fullPage })
}

async function captureHovering(page: Page, target: Locator, name: string): Promise<void> {
  await target.hover()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`filter-on/${name}`) })
}

async function expectEventsTab(page: Page, expected: { chip?: string; pidChip?: string }): Promise<void> {
  await expect(page).toHaveURL(new RegExp(`/analyses/${ID}/events`))
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  const chips = page.locator('.filter-chip')
  if (expected.chip) await expect(chips.filter({ hasText: expected.chip })).toBeVisible()
  if (expected.pidChip) await expect(chips.filter({ hasText: expected.pidChip })).toBeVisible()
}

/** Row actions must not make a table taller: the same rows, with every action hidden, are exactly as high. */
async function expectRowsNotTallerThanWithoutActions(page: Page, rows: string): Promise<void> {
  const heights = () => page.locator(rows).evaluateAll((elements) => elements.map((element) => Math.round(element.getBoundingClientRect().height * 10) / 10))
  const withActions = await heights()
  expect(withActions.length).toBeGreaterThan(0)
  const hidingStyle = await page.addStyleTag({ content: '.filter-events-button { display: none !important }' })
  const withoutActions = await heights()
  await hidingStyle.evaluate((style) => (style as Element).remove())
  expect(withActions).toEqual(withoutActions)
}

async function expectActionsInsideTheirCells(page: Page): Promise<void> {
  const clipped = await page.locator('.filter-events-button').evaluateAll((buttons) =>
    buttons
      .filter((button) => {
        const cell = button.closest('td')
        if (!cell) return false
        const box = button.getBoundingClientRect()
        const around = cell.getBoundingClientRect()
        return box.right > around.right + 1 || box.bottom > around.bottom + 1 || box.top < around.top - 1
      })
      .map((button) => button.getAttribute('aria-label')),
  )
  expect(clipped, 'actions that spill out of their cell').toEqual([])
}

function sampleRelated(count: number, pid: number) {
  return sampleEvents()
    .filter((event) => event.process?.pid === pid && event.kind === 'event')
    .slice(0, count)
    .map(({ id, time, lane, action, summary, process }) => ({
      id,
      time,
      lane: lane ?? 'api',
      action: action ?? '',
      summary: summary ?? '',
      process: process?.pid == null ? null : { pid: process.pid, name: process.name },
    }))
}

// ---------- Network ----------

function networkView(): NetworkView {
  const real = realView<NetworkView>('network')
  const dns = real.dns.items.map((row, index) => (index === 1 || index === 4 ? { ...row, process: index === 4 ? BENIGN : CMD } : row))
  const flows = real.flows.items.slice(0, 12).map((row, index) => ({ ...row, destination_port: index === 2 ? 53 : row.destination_port, process: index === 2 ? BENIGN : index === 5 ? CMD : row.process }))
  const tls = [
    { event_id: 'tls-1', time: '2026-10-13T15:39:33.872000Z', server_name: 'c2.evil-updates.net', ja3: 'e7d705a3286e19ea42f587b344ee6865', ja3s: '4b6dee3bd2b7c9a2f1b4d9e3c0a1f2d8', process: BENIGN },
    { event_id: 'tls-2', time: '2026-10-13T15:39:35.100000Z', server_name: null, ja3: null, ja3s: null, process: null },
  ]
  return { ...real, dns: { items: dns, total: dns.length }, flows: { items: flows, total: 210 }, tls: { items: tls, total: tls.length } }
}

function withNetwork(network: NetworkView): Views {
  return { network: { body: network } }
}

async function openNetwork(page: Page, subTab: string, network = networkView()): Promise<void> {
  await open(page, 'network', withNetwork(network))
  await expect(page.getByRole('tab', { name: /^DNS/ })).toBeVisible()
  if (subTab !== 'DNS') await page.getByRole('tab', { name: new RegExp(`^${subTab}`) }).click()
  await expect(page.locator('tbody tr').first()).toBeVisible()
}

test('filter-on-network-dns-rest', async ({ page }) => {
  await openNetwork(page, 'DNS')
  await expect(page.locator('tbody tr')).toHaveCount(5)
  await expect(page.getByRole('button', { name: 'Show events with pid: 9708' })).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Show events with pid: 2476' })).toHaveCount(1)
  await expectRowsNotTallerThanWithoutActions(page, 'tbody tr')
})

test('filter-on-network-dns-visible', async ({ page }) => {
  await openNetwork(page, 'DNS')
  await expectActionsInsideTheirCells(page)
  await capture(page, 'a1-network-dns')
  await captureHovering(page, page.getByRole('button', { name: 'Show events with dns.question.name: tartarus-selftest.example' }), 'a2-network-dns-hover-action')
  await page.getByRole('button', { name: 'Show events with pid: 2476' }).focus()
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Tab')
  await capture(page, 'a3-network-dns-keyboard-focus')
})

test('filter-on-network-dns-click', async ({ page }) => {
  await openNetwork(page, 'DNS')
  await page.getByRole('button', { name: 'Show events with dns.question.name: tartarus-selftest.example' }).click()
  await expectEventsTab(page, { chip: 'dns.question.name: tartarus-selftest.example' })
  await expect(page.locator('.event-table__count')).toHaveText('5 of 5 events')
  await capture(page, 'b-network-dns-then-events')
})

test('filter-on-network-process-click', async ({ page }) => {
  await openNetwork(page, 'DNS')
  await page.getByRole('button', { name: 'Show events with pid: 2476' }).click()
  await expectEventsTab(page, { pidChip: 'pid: 2476 (cmd.exe)' })
  await capture(page, 'b2-network-process-then-events')
})

test('filter-on-network-http-and-flows', async ({ page }) => {
  await openNetwork(page, 'HTTP')
  await expectActionsInsideTheirCells(page)
  await expectRowsNotTallerThanWithoutActions(page, 'tbody tr')
  await capture(page, 'c1-network-http')
  await page.getByRole('tab', { name: /^FLOWS/ }).click()
  await expect(page.locator('tbody tr').first()).toBeVisible()
  await expectActionsInsideTheirCells(page)
  await capture(page, 'c2-network-flows')
  await expectRowsNotTallerThanWithoutActions(page, 'tbody tr')
})

test('filter-on-network-flows-click', async ({ page }) => {
  await openNetwork(page, 'FLOWS')
  await page.getByRole('button', { name: 'Show events with destination.ip: 192.168.150.1 and destination.port: 53' }).first().click()
  await expectEventsTab(page, { chip: 'destination.port: 53' })
  await expect(page.locator('.filter-chip').filter({ hasText: 'destination.ip: 192.168.150.1' })).toBeVisible()
  await capture(page, 'c3-network-flows-then-events')
})

test('filter-on-network-tls-and-hosts', async ({ page }) => {
  await openNetwork(page, 'TLS')
  await capture(page, 'c4-network-tls')
  await page.getByRole('tab', { name: /^HOSTS/ }).click()
  await expect(page.locator('tbody tr').first()).toBeVisible()
  await expectActionsInsideTheirCells(page)
  await capture(page, 'c5-network-hosts')
})

// ---------- Artifacts ----------

async function openArtifacts(page: Page, subTab: RegExp, views: Views = {}): Promise<void> {
  await open(page, 'artifacts', views)
  await expect(page.getByRole('tab', { name: /^DROPPED FILES/ })).toBeVisible()
  await page.getByRole('tab', { name: subTab }).click()
}

test('filter-on-artifacts-dropped', async ({ page }) => {
  await openArtifacts(page, /^DROPPED FILES/)
  await expect(page.getByRole('button', { name: /^Show events with file\.path/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Show events with file\.hash\.sha256/ })).toBeVisible()
  await expectActionsInsideTheirCells(page)
  await expectRowsNotTallerThanWithoutActions(page, VISIBLE_ROWS)
  await capture(page, 'd1-artifacts-dropped')
})

test('filter-on-artifacts-dropped-click', async ({ page }) => {
  // The report's own dropped file has no event in the sample index; this path has three.
  const path = 'C:\\Users\\Public\\Libraries\\payload.bin'
  const real = realView<ArtifactsView>('artifacts')
  await openArtifacts(page, /^DROPPED FILES/, { artifacts: { body: { ...real, dropped: [{ ...real.dropped[0]!, guest_path: path }] } } })
  await page.getByRole('button', { name: `Show events with file.path: ${path}` }).click()
  await expectEventsTab(page, { chip: 'file.path: C:\\Users\\Public' })
  await expect(page.locator('.event-table__count')).toHaveText('3 of 3 events')
  await capture(page, 'd2-artifacts-dropped-then-events')
})

test('filter-on-artifacts-iocs', async ({ page }) => {
  await openArtifacts(page, /^IOCs/)
  await expect(PANEL_ROWS(page).first()).toBeVisible()
  await expect(PANEL_ROWS(page).filter({ hasText: 'mutex' }).locator('.filter-events-button')).toHaveCount(0)
  await expectActionsInsideTheirCells(page)
  await expectRowsNotTallerThanWithoutActions(page, VISIBLE_ROWS)
  await capture(page, 'd3-artifacts-iocs')
})

test('filter-on-artifacts-iocs-domain-click', async ({ page }) => {
  await openArtifacts(page, /^IOCs/)
  await page.getByRole('button', { name: 'Show events with domain: tartarus-selftest.example' }).click()
  await expectEventsTab(page, { chip: 'domain: tartarus-selftest.example' })
  await capture(page, 'd4-artifacts-ioc-domain-then-events')
})

function registryView(): RegistryView {
  const real = realView<RegistryView>('registry')
  const changes = real.keys[0]!.changes
  return {
    total: changes.length + 1,
    keys: [
      { hive: 'HKCU', key: 'Software\\Microsoft\\Windows\\CurrentVersion\\Run', changes: [{ ...changes[1]!, event_id: 'reg-run', value_name: 'Updater', action: 'registry-value-set', data: ['C:\\Users\\Analyst\\updater.exe'] }] },
      ...real.keys,
    ],
  }
}

test('filter-on-registry', async ({ page }) => {
  await openArtifacts(page, /^REGISTRY/, { registry: { body: registryView() } })
  await expect(PANEL_ROWS(page).first()).toBeVisible()
  await expectActionsInsideTheirCells(page)
  await expectRowsNotTallerThanWithoutActions(page, VISIBLE_ROWS)
  await capture(page, 'e1-artifacts-registry')
  await page.getByRole('button', { name: /^Show events with registry\.hive: HKCU and registry\.key: Software\\Microsoft\\Windows\\CurrentVersion\\Run/ }).click()
  await expectEventsTab(page, { chip: 'registry.value: Updater' })
  await capture(page, 'e2-artifacts-registry-then-events')
})

// ---------- Processes ----------

test('filter-on-processes', async ({ page }) => {
  await open(page, 'processes')
  await expect(page.locator('.process-details__apis')).toBeVisible()
  const button = page.getByRole('button', { name: 'Show events with pid: 9708' })
  await expect(button).toBeVisible()
  await capture(page, 'f1-processes-selected')
  await captureHovering(page, button, 'f2-processes-hover-action')
  await button.click()
  await expectEventsTab(page, { pidChip: 'pid: 9708 (benign.exe)' })
  await capture(page, 'f3-processes-then-events')
})

test('filter-on-processes-selection-stays-local', async ({ page }) => {
  await open(page, 'processes')
  await expect(page.locator('.process-details__apis')).toBeVisible()
  await page.getByRole('button', { name: 'TREE' }).click()
  await page.locator('.q-tree__node-header', { hasText: 'cmd.exe' }).click()
  await expect(page.locator('.process-details__title')).toContainText('cmd.exe')
  await expect(page.getByRole('button', { name: 'Show events with pid: 2476' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('pid')).toBeNull()
  await capture(page, 'f4-processes-tree-selected')
})

// ---------- Detections ----------

function detectionsView(): DetectionsView {
  const real = realView<DetectionsView>('detections')
  const related = { recon_systeminfo: sampleRelated(6, 9708), network_http: sampleRelated(3, 2476) }
  return {
    ...real,
    groups: real.groups.map((group) => ({
      ...group,
      detections: group.detections.map((detection) => {
        const events = related[detection.name as keyof typeof related]
        if (!events) return detection
        const total = detection.name === 'recon_systeminfo' ? 40 : events.length
        return { ...detection, related_events: events, related_event_total: total }
      }),
    })),
  }
}

test('filter-on-detections', async ({ page }) => {
  await open(page, 'detections', { detections: { body: detectionsView() } })
  await expect(page.locator('.detection-detail__show-events')).toBeVisible()
  await expect(page.locator('.detection-detail__events-count')).toHaveText('6 of 40 shown')
  await capture(page, 'g1-detections')
  await page.locator('.detection-detail__show-events').click()
  await expect(page).toHaveURL(new RegExp(`/analyses/${ID}/events`))
  await expect(page.locator('[data-event-id]')).toHaveCount(6)
  await expect(page.getByRole('combobox', { name: 'Query' })).toHaveValue(/^event\.id:\(/)
  await capture(page, 'g2-detections-then-events-id-query')
})

test('filter-on-detections-rule', async ({ page }) => {
  await open(page, 'detections', { detections: { body: detectionsView() } })
  await page.locator('.detection-entry', { hasText: 'network_http' }).click()
  await expect(page.locator('.detection-detail__name')).toHaveText('network_http')
  await capture(page, 'g3-detections-network-http', true)
  await page.locator('.detection-detail__rule-filter').click()
  await expectEventsTab(page, { chip: 'rule.name: network_http' })
  await capture(page, 'g4-detections-rule-then-events')
})

test('filter-on-detections-without-events', async ({ page }) => {
  await open(page, 'detections', { detections: { body: detectionsView() } })
  await page.locator('.detection-entry', { hasText: 'language_check_registry' }).click()
  await expect(page.locator('.detection-detail__show-events')).toHaveCount(0)
  await expect(page.locator('.detection-detail__rule-filter')).toBeVisible()
  await capture(page, 'g5-detections-no-triggering-events', true)
})

// ---------- A row whose process is unknown ----------

test('filter-on-unknown-process', async ({ page }) => {
  await openNetwork(page, 'DNS')
  const unknown = page.locator('tbody tr').first()
  await expect(unknown.locator('td').last()).toHaveText('–')
  await expect(unknown.getByRole('button', { name: /pid/ })).toHaveCount(0)
  await expect(unknown.getByRole('button', { name: /^Show events with dns\.question\.name/ })).toHaveCount(1)
  await capture(page, 'h-network-unknown-process')
})

// ---------- Narrow window and long values ----------

test('filter-on-narrow-network-http', async ({ page }) => {
  await page.setViewportSize(NARROW)
  const real = networkView()
  await openNetwork(page, 'HTTP', { ...real, http: { items: [{ ...real.http.items[0]!, url: LONG_URL, host: LONG_DOMAIN, process: BENIGN }, real.http.items[1]!], total: 2 } })
  await expectNoHorizontalOverflow(page)
  await expectActionsInsideTheirCells(page)
  await capture(page, 'i1-narrow-network-http-long-url')
  await page.locator('.tt-table-scroll').evaluate((scroller) => scroller.scrollTo({ left: scroller.scrollWidth }))
  await expect(page.getByRole('button', { name: 'Show events with pid: 9708' })).toBeVisible()
  await capture(page, 'i1b-narrow-network-http-scrolled-to-process')
})

test('filter-on-narrow-artifacts', async ({ page }) => {
  await page.setViewportSize(NARROW)
  const real = realView<ArtifactsView>('artifacts')
  const dropped = [{ ...real.dropped[0]!, guest_path: LONG_PATH }, ...real.dropped.slice(1)]
  await openArtifacts(page, /^DROPPED FILES/, { artifacts: { body: { ...real, dropped } } })
  await expectNoHorizontalOverflow(page)
  await expectActionsInsideTheirCells(page)
  await capture(page, 'i2-narrow-artifacts-long-path')
})

test('filter-on-narrow-detections-and-processes', async ({ page }) => {
  await page.setViewportSize(NARROW)
  await open(page, 'detections', { detections: { body: detectionsView() } })
  await expect(page.locator('.detection-detail__show-events')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('filter-on/i3-narrow-detections'), fullPage: true })
  await page.goto(`/analyses/${ID}/processes`)
  await expect(page.locator('.process-details__apis')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await capture(page, 'i4-narrow-processes', true)
})
