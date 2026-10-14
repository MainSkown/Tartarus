import type { Page } from '@playwright/test'
import type { ProcessDetail, ProcessNode, ProcessTree } from '../../src/api/types.gen'
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
const ROUTE = `/analyses/${ID}/processes`
const PROCESS_URL = (url: URL): boolean => new RegExp(`^/api/analyses/${ID}/processes/\\d+$`).test(url.pathname)
const LONG_COMMAND_LINE = `"C:\\Users\\Analyst\\AppData\\Local\\Temp\\${'nested_directory_'.repeat(12)}loader.exe" -EncodedCommand ${'SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA'.repeat(10)} --config=${'a'.repeat(120)}`

async function openProcesses(page: Page, processes?: ViewMock, detail?: (pid: number) => ViewMock | undefined): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockViews(page, processes ? { processes } : {})
  if (detail) {
    await page.route(PROCESS_URL, async (route) => {
      const pid = Number(new URL(route.request().url()).pathname.split('/').pop())
      const mock = detail(pid) ?? {}
      if (mock.delayMs) await new Promise((resolve) => setTimeout(resolve, mock.delayMs))
      await route.fulfill({ status: mock.status ?? 200, json: mock.body })
    })
  }
  await page.goto(ROUTE)
}

async function expectGraphDrawn(page: Page): Promise<void> {
  await expect(page.locator('.process-graph__canvas canvas').first()).toBeAttached()
  await expect(page.locator('.process-details__apis')).toBeVisible()
  await waitForTransitions(page)
}

/** The default 1280x720 window: the tab must fill it exactly, with nothing pushed below the fold. */
async function expectFitsViewport(page: Page): Promise<void> {
  const { scrollHeight, innerHeight } = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    innerHeight: window.innerHeight,
  }))
  expect(scrollHeight, `page scrolls vertically: ${scrollHeight}px of content in a ${innerHeight}px window`).toBeLessThanOrEqual(innerHeight)
  for (const selector of ['.processes-tab__body > :first-child', '.process-details']) {
    const box = (await page.locator(selector).boundingBox())!
    expect(box.y + box.height, `${selector} reaches below the window`).toBeLessThanOrEqual(innerHeight)
  }
  const canvas = page.locator('.process-graph__canvas, .process-tree-list')
  const canvasBox = (await canvas.boundingBox())!
  const panelBox = (await page.locator('.process-details').boundingBox())!
  expect(Math.abs(canvasBox.y + canvasBox.height - (panelBox.y + panelBox.height)), 'canvas and panel end at the same height').toBeLessThanOrEqual(1)
}

async function openSubTab(page: Page, label: string): Promise<void> {
  const tab = page.locator('.process-details').getByRole('tab', { name: label })
  await tab.click()
  await expect(tab).toHaveAttribute('aria-selected', 'true')
}

async function snapshot(page: Page, name: string): Promise<Buffer> {
  // A page scrolled by an earlier click would be captured with its fixed header in the middle.
  await page.evaluate(() => window.scrollTo(0, 0))
  return page.screenshot({ path: screenshotPath(name), fullPage: true })
}

function syntheticNode(pid: number, overrides: Partial<ProcessNode> = {}): ProcessNode {
  return {
    entity_id: `${ID}:${pid}@2026-10-13T15:39:50.000Z`,
    pid,
    ppid: null,
    name: `process_${pid}.exe`,
    executable: `C:\\Windows\\System32\\process_${pid}.exe`,
    command_line: `process_${pid}.exe /run`,
    start: '2026-10-13T15:39:50.000000Z',
    end: '2026-10-13T15:39:52.500000Z',
    integrity: null,
    max_severity: null,
    detection_count: 0,
    injected_into: [],
    network_hosts: [],
    event_counts_by_lane: { api: 12, process: 1 },
    tags: [],
    note_count: 0,
    children: [],
    ...overrides,
  }
}

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'] as const

function syntheticTree(depth: number, fanout: number, pid = { next: 1000 }): ProcessNode {
  const node = syntheticNode(pid.next++)
  if (pid.next % 3 === 0) {
    node.max_severity = SEVERITIES[pid.next % SEVERITIES.length]!
    node.detection_count = 1 + (pid.next % 7)
  }
  if (depth > 1) node.children = Array.from({ length: fanout }, () => syntheticTree(depth - 1, fanout, pid))
  return node
}

function flatten(node: ProcessNode): ProcessNode[] {
  return [node, ...node.children.flatMap(flatten)]
}

function detailFor(processes: ProcessNode[]): (pid: number) => ViewMock {
  return (pid) => {
    const node = processes.find((process) => process.pid === pid)!
    const fields: Partial<ProcessNode> = { ...node }
    delete fields.children
    const detail: ProcessDetail = { ...(fields as Omit<ProcessNode, 'children'>), modules: [], top_apis: [{ name: 'NtClose', count: 40 }], events: [], event_total: 0 }
    return { body: detail }
  }
}

function treeOf(...roots: ProcessNode[]): ProcessTree {
  return { roots, total: roots.flatMap(flatten).length }
}

test('processes-default', async ({ page }) => {
  await openProcesses(page)
  await expectGraphDrawn(page)
  await expectFitsViewport(page)
  await snapshot(page, 'processes-default')
})

test('processes-modules', async ({ page }) => {
  await openProcesses(page)
  await expectGraphDrawn(page)
  await openSubTab(page, 'MODULES')
  await expect(page.getByText('0x7ffd9d790000')).toBeVisible()
  await expectFitsViewport(page)
  await snapshot(page, 'processes-modules')
})

test('processes-events', async ({ page }) => {
  await openProcesses(page)
  await expectGraphDrawn(page)
  await openSubTab(page, 'EVENTS')
  await expect(page.getByText('DNS query for tartarus-selftest.example')).toBeVisible()
  await expectFitsViewport(page)
  await snapshot(page, 'processes-events')
})

test('processes-second-process-selected', async ({ page }) => {
  await openProcesses(page)
  await expectGraphDrawn(page)
  await page.getByRole('button', { name: 'TREE' }).click()
  await page.locator('.q-tree__node-header', { hasText: 'cmd.exe' }).click()
  await expect(page.locator('.process-details__title')).toHaveText('cmd.exe (2476)')
  await page.getByRole('button', { name: 'GRAPH' }).click()
  await expect(page.locator('.process-graph__canvas canvas').first()).toBeAttached()
  await waitForTransitions(page)
  await expectFitsViewport(page)
  await snapshot(page, 'processes-second-process-selected')
})

test('processes-tree', async ({ page }) => {
  await openProcesses(page)
  await expectGraphDrawn(page)
  await page.getByRole('button', { name: 'TREE' }).click()
  await expect(page.locator('.q-tree__node-header')).toHaveCount(2)
  await waitForTransitions(page)
  await expectFitsViewport(page)
  await snapshot(page, 'processes-tree')
})

test('processes-loading', async ({ page }) => {
  await openProcesses(page, { delayMs: 30_000, body: realView('processes') })
  await expect(page.locator('.loader')).toBeVisible()
  await snapshot(page, 'processes-loading')
})

test('processes-empty', async ({ page }) => {
  await openProcesses(page, { body: { roots: [], total: 0 } })
  await expect(page.getByText('> no processes recorded')).toBeVisible()
  await snapshot(page, 'processes-empty')
})

test('processes-error', async ({ page }) => {
  await openProcesses(page, { status: 500, body: errorEnvelope('internal_error', 'opensearch is unavailable') })
  await expect(page.getByText('failed to load: opensearch is unavailable')).toBeVisible()
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await snapshot(page, 'processes-error')
})

test('processes-detail-loading', async ({ page }) => {
  await openProcesses(page, undefined, () => ({ delayMs: 30_000 }))
  await expect(page.locator('.process-details .loader')).toBeVisible()
  await expect(page.locator('.process-graph__canvas canvas').first()).toBeAttached()
  await expectFitsViewport(page)
  await snapshot(page, 'processes-detail-loading')
})

test('processes-detail-error', async ({ page }) => {
  await openProcesses(page, undefined, () => ({ status: 500, body: errorEnvelope('internal_error', 'process lookup timed out') }))
  await expect(page.locator('.process-details').getByText('failed to load: process lookup timed out')).toBeVisible()
  await expect(page.locator('.process-graph__canvas canvas').first()).toBeAttached()
  await expectFitsViewport(page)
  await snapshot(page, 'processes-detail-error')
})

test('processes-injection-and-hosts', async ({ page }) => {
  const victim = syntheticNode(2000, { name: 'explorer.exe', max_severity: 'critical', detection_count: 3, network_hosts: ['203.0.113.7', 'c2.example.org'] })
  const injector = syntheticNode(1900, {
    name: 'dropper.exe',
    max_severity: 'high',
    detection_count: 4,
    injected_into: [2000],
    network_hosts: ['c2.example.org'],
    children: [syntheticNode(1950, { name: 'helper.exe' })],
  })
  const processes = treeOf(injector, victim)
  await openProcesses(page, { body: processes }, detailFor(flatten(injector).concat(flatten(victim))))
  await expectGraphDrawn(page)
  await page.getByText('HOSTS', { exact: true }).click()
  await expect(page.locator('.process-details__apis')).toBeVisible()
  await expectFitsViewport(page)
  await snapshot(page, 'processes-injection-and-hosts')
})

test('processes-wide-tree-pan-zoom', async ({ page }) => {
  const root = syntheticTree(5, 4)
  const all = flatten(root)
  await openProcesses(page, { body: treeOf(root) }, detailFor(all))
  await expectGraphDrawn(page)
  await expectNoHorizontalOverflow(page)
  await expectFitsViewport(page)
  const canvas = page.locator('.process-graph__canvas')
  const box = (await canvas.boundingBox())!
  await snapshot(page, 'processes-wide-tree-fit')

  for (let step = 0; step < 9; step++) await page.getByRole('button', { name: 'Zoom in' }).click()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 - 200, box.y + box.height / 2 - 60, { steps: 5 })
  await page.mouse.up()
  await expectNoHorizontalOverflow(page)
  expect((await canvas.boundingBox())!.width, 'the canvas keeps its width while zoomed').toBe(box.width)
  await snapshot(page, 'processes-wide-tree-zoomed-and-panned')
})

test('processes-wide-tree-as-tree', async ({ page }) => {
  const root = syntheticTree(5, 3)
  await openProcesses(page, { body: treeOf(root) }, detailFor(flatten(root)))
  await expectGraphDrawn(page)
  await page.getByRole('button', { name: 'TREE' }).click()
  await expect(page.locator('.q-tree__node-header').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await expectFitsViewport(page)
  await snapshot(page, 'processes-wide-tree-as-tree')
})

function longCommandTree(): ProcessTree {
  return treeOf(
    syntheticNode(4242, {
      name: 'a_really_long_process_name_that_keeps_going_and_going_until_it_has_to_wrap_somewhere.exe',
      executable: `C:\\Users\\Analyst\\AppData\\Local\\Temp\\${'nested_directory_'.repeat(12)}loader.exe`,
      command_line: LONG_COMMAND_LINE,
      max_severity: 'critical',
      detection_count: 12,
      network_hosts: [`${'very-long-subdomain-'.repeat(6)}example.org`],
    }),
  )
}

test('processes-long-command-line', async ({ page }) => {
  const processes = longCommandTree()
  await openProcesses(page, { body: processes }, detailFor(flatten(processes.roots[0]!)))
  await expectGraphDrawn(page)
  await expectNoHorizontalOverflow(page)
  await expectFitsViewport(page)
  await snapshot(page, 'processes-long-command-line')
})

test('processes-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  await openProcesses(page)
  await expectGraphDrawn(page)
  const graph = (await page.locator('.process-graph').boundingBox())!
  const details = (await page.locator('.process-details').boundingBox())!
  expect(details.y, 'the details panel stacks under the graph').toBeGreaterThanOrEqual(graph.y + graph.height)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'processes-narrow-600')
})

test('processes-narrow-600-tree', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  await openProcesses(page)
  await expectGraphDrawn(page)
  await page.getByRole('button', { name: 'TREE' }).click()
  await expect(page.locator('.q-tree__node-header').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'processes-narrow-600-tree')
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`processes tab does not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const processes = longCommandTree()
    await openProcesses(page, { body: processes }, detailFor(flatten(processes.roots[0]!)))
    await expectGraphDrawn(page)
    await expectNoHorizontalOverflow(page)
    await page.getByRole('button', { name: 'TREE' }).click()
    await expect(page.locator('.q-tree__node-header').first()).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })
}
