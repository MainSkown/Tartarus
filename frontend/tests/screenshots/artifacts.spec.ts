import type { Page } from '@playwright/test'
import type { Artifact, ArtifactsView, IocsView, RegistryView } from '../../src/api/types.gen'
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
  sha256Of,
  test,
  waitForTransitions,
  type ViewMock,
  type ViewName,
} from './fixtures'

const ID = 45
const SUB_TABS = ['DROPPED', 'PAYLOADS', 'PROCESS DUMPS', 'MEMORY', 'REGISTRY', 'IOCs']
const LONG_PATH = `C:\\Users\\Administrator\\AppData\\Local\\Temp\\${'deeply_nested_directory_name\\'.repeat(8)}payload_with_a_very_long_file_name.bin`
const SERVER_ERROR: ViewMock = { status: 500, body: errorEnvelope('internal_error', 'OpenSearch is not answering') }

type Overrides = Partial<Record<ViewName, ViewMock>>

async function openArtifacts(page: Page, overrides: Overrides = {}, subTab?: string): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockViews(page, overrides)
  await page.goto(`/analyses/${ID}/artifacts`)
  const waitsForNothing = Object.values(overrides).some((mock) => mock.delayMs || mock.status)
  if (subTab) {
    await expect(page.locator('.artifact-sub-tabs').getByRole('tab').first()).toBeVisible()
    await page.locator('.artifact-sub-tabs').getByRole('tab', { name: new RegExp(`^${subTab}`) }).click()
  }
  if (!waitsForNothing) await expect(page.locator('.artifact-panel:visible .loader')).toHaveCount(0)
  await waitForTransitions(page)
}

function artifact(index: number, overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: `artifact${index}`,
    name: `dropped_file_${index}.${index % 3 === 0 ? 'dll' : 'exe'}`,
    size: 1024 * (index + 1) * 7,
    sha256: sha256Of(index + 16),
    md5: null,
    type: 'PE32 executable (GUI) Intel 80386, for MS Windows',
    cape_type: null,
    yara: [],
    source_process: { pid: 1000 + index, name: 'invoice_scan.exe' },
    guest_path: `C:\\Users\\Analyst\\AppData\\Roaming\\Microsoft\\${index}\\dropped_file_${index}.exe`,
    downloadable: true,
    ...overrides,
  }
}

function emptyArtifacts(): ArtifactsView {
  return { ...realView<ArtifactsView>('artifacts'), dropped: [], payloads: [], procdumps: [], memory_dump: null, configs: [] }
}

function richArtifacts(): ArtifactsView {
  const dropped = Array.from({ length: 40 }, (_, index) =>
    artifact(index, {
      yara: index % 4 === 0 ? ['Emotet_loader', 'UPX_packed', 'a_rule_with_a_rather_long_name_that_keeps_going'] : [],
      guest_path: index === 2 ? LONG_PATH : artifact(index).guest_path,
      name: index === 3 ? `${'a_very_long_file_name_'.repeat(8)}.exe` : artifact(index).name,
      downloadable: index !== 5,
      source_process: index % 5 === 0 ? null : artifact(index).source_process,
      size: index === 6 ? null : artifact(index).size,
    }),
  )
  return {
    ...realView<ArtifactsView>('artifacts'),
    dropped,
    payloads: [
      artifact(100, { name: 'unpacked_payload.bin', cape_type: 'AgentTesla Payload', yara: ['AgentTesla'], guest_path: null }),
      artifact(101, { name: 'stage2.dll', cape_type: 'Formbook Config', yara: [], downloadable: false }),
    ],
    procdumps: dropped.slice(0, 6).map((file, index) => ({ ...file, id: `dump${index}`, name: `${1000 + index}.dmp` })),
    memory_dump: artifact(200, { name: 'memory.dmp', size: 2147483648, type: null, sha256: null, guest_path: null, source_process: null }),
    configs: [
      {
        id: 'cfg-agenttesla',
        family: 'AgentTesla',
        data: {
          c2: ['smtp.evil.example:587', `http://${'subdomain.'.repeat(10)}evil.example/gate.php?token=${'ab12'.repeat(30)}`],
          username: 'exfil@evil.example',
          keylogger: true,
          interval_s: 300,
          nested: { mutex: 'Global\\8f3a1c', botnet: 'campaign-17' },
        },
      },
    ],
  }
}

function richRegistry(): RegistryView {
  const base = realView<RegistryView>('registry').keys[0]!.changes
  const keys = Array.from({ length: 14 }, (_, index) => ({
    key: index === 3 ? `Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\${'VeryLongSubKeyName\\'.repeat(6)}Run` : `Software\\Vendor${index}\\Settings`,
    hive: index % 2 ? 'HKLM' : 'HKCU',
    changes: base.map((change, position) => ({
      ...change,
      event_id: `${index}-${position}`,
      data: change.data.length ? [`C:\\Users\\Analyst\\${'very_long_data_segment\\'.repeat(6)}updater.exe`] : [],
    })),
  }))
  return { keys, total: keys.length * base.length }
}

function richIocs(): IocsView {
  const real = realView<IocsView>('iocs').iocs
  const long = [
    { ...real[0]!, type: 'url' as const, value: `http://${'subdomain.'.repeat(8)}evil.example/gate.php?id=${'0123456789abcdef'.repeat(12)}`, context: `POST ${'a very verbose request description '.repeat(5)}` },
    { ...real[0]!, type: 'ip' as const, value: '203.0.113.77', context: 'Connected to 203.0.113.77:443', count: 214 },
  ]
  return { iocs: [...real, ...long], truncated_types: ['domain', 'url'] }
}

test.describe('real data', () => {
  const REAL: { name: string; tab: string; expects: string }[] = [
    { name: 'artifacts-dropped', tab: 'DROPPED', expects: 'tartarus-benign.txt' },
    { name: 'artifacts-payloads-none', tab: 'PAYLOADS', expects: 'no payloads or configs were extracted' },
    { name: 'artifacts-dumps', tab: 'PROCESS DUMPS', expects: 'cmd.exe' },
    { name: 'artifacts-registry', tab: 'REGISTRY', expects: 'HKCU\\Software\\Tartarus' },
    { name: 'artifacts-iocs', tab: 'IOCs', expects: 'tartarus-selftest.example' },
  ]
  for (const { name, tab, expects } of REAL) {
    test(name, async ({ page }) => {
      await openArtifacts(page, {}, tab)
      await expect(page.getByText(expects).first()).toBeVisible()
      await page.screenshot({ path: screenshotPath(name), fullPage: true })
    })
  }
})

test.describe('loading', () => {
  const SLOW: ViewMock = { delayMs: 4000 }
  const cases: { name: string; overrides: Overrides; tab?: string }[] = [
    { name: 'artifacts-loading-dropped', overrides: { artifacts: SLOW } },
    { name: 'artifacts-loading-registry', overrides: { registry: SLOW }, tab: 'REGISTRY' },
    { name: 'artifacts-loading-iocs', overrides: { iocs: SLOW }, tab: 'IOCs' },
  ]
  for (const { name, overrides, tab } of cases) {
    test(name, async ({ page }) => {
      await openArtifacts(page, overrides, tab)
      await expect(page.locator('.artifact-panel:visible .loader')).toBeVisible()
      await page.screenshot({ path: screenshotPath(name) })
    })
  }
})

test.describe('empty', () => {
  const cases: { name: string; overrides: Overrides; tab: string; message: string }[] = [
    { name: 'artifacts-empty-dropped', overrides: { artifacts: { body: emptyArtifacts() } }, tab: 'DROPPED', message: 'no files were dropped' },
    { name: 'artifacts-empty-payloads', overrides: { artifacts: { body: emptyArtifacts() } }, tab: 'PAYLOADS', message: 'no payloads or configs were extracted' },
    { name: 'artifacts-empty-dumps', overrides: { artifacts: { body: emptyArtifacts() } }, tab: 'PROCESS DUMPS', message: 'no process dumps were captured' },
    { name: 'artifacts-empty-registry', overrides: { registry: { body: { keys: [], total: 0 } } }, tab: 'REGISTRY', message: 'no registry changes were recorded' },
    { name: 'artifacts-empty-iocs', overrides: { iocs: { body: { iocs: [], truncated_types: [] } } }, tab: 'IOCs', message: 'no indicators were extracted' },
  ]
  for (const { name, overrides, tab, message } of cases) {
    test(name, async ({ page }) => {
      await openArtifacts(page, overrides, tab)
      await expect(page.getByText(message)).toBeVisible()
      await page.screenshot({ path: screenshotPath(name) })
    })
  }
})

test.describe('error', () => {
  const cases: { name: string; overrides: Overrides; tab: string }[] = [
    { name: 'artifacts-error-dropped', overrides: { artifacts: SERVER_ERROR }, tab: 'DROPPED' },
    { name: 'artifacts-error-registry', overrides: { registry: SERVER_ERROR }, tab: 'REGISTRY' },
    { name: 'artifacts-error-iocs', overrides: { iocs: SERVER_ERROR }, tab: 'IOCs' },
  ]
  for (const { name, overrides, tab } of cases) {
    test(name, async ({ page }) => {
      await openArtifacts(page, overrides, tab)
      await expect(page.locator('.artifact-panel:visible').getByText('OpenSearch is not answering')).toBeVisible()
      await expect(page.locator('.artifact-panel:visible').getByRole('button', { name: '[RETRY]' })).toBeVisible()
      await page.screenshot({ path: screenshotPath(name) })
    })
  }
})

const RICH: Overrides = {
  artifacts: { body: richArtifacts() },
  registry: { body: richRegistry() },
  iocs: { body: richIocs() },
}

test.describe('rich data', () => {
  test('artifacts-rich-dropped', async ({ page }) => {
    await openArtifacts(page, RICH, 'DROPPED')
    await expect(page.getByText('dropped_file_39.dll')).toBeVisible()
    await expect(page.locator('.artifact-panel:visible .download-unavailable')).toHaveCount(1)
    await page.screenshot({ path: screenshotPath('artifacts-rich-dropped'), fullPage: true })
  })

  test('artifacts-rich-payloads', async ({ page }) => {
    await openArtifacts(page, RICH, 'PAYLOADS')
    await expect(page.locator('.config-family')).toHaveText('AgentTesla')
    await page.screenshot({ path: screenshotPath('artifacts-rich-payloads'), fullPage: true })
  })

  test('artifacts-rich-dumps', async ({ page }) => {
    await openArtifacts(page, RICH, 'PROCESS DUMPS')
    await expect(page.locator('.artifact-panel:visible tbody tr')).toHaveCount(6)
    await expect(page.getByText('memory.dmp')).toHaveCount(0)
    await page.screenshot({ path: screenshotPath('artifacts-rich-dumps'), fullPage: true })
  })

  test('artifacts-rich-registry', async ({ page }) => {
    await openArtifacts(page, RICH, 'REGISTRY')
    await expect(page.locator('details')).toHaveCount(14)
    await page.screenshot({ path: screenshotPath('artifacts-rich-registry-folded'), fullPage: true })
    await page.locator('summary').nth(3).click()
    await page.locator('summary').nth(0).click()
    await page.screenshot({ path: screenshotPath('artifacts-rich-registry-open'), fullPage: true })
  })

  test('artifacts-rich-iocs', async ({ page }) => {
    await openArtifacts(page, RICH, 'IOCs')
    await expect(page.locator('.truncated-note')).toBeVisible()
    await page.screenshot({ path: screenshotPath('artifacts-rich-iocs'), fullPage: true })
  })

  test('artifacts-iocs-filtered', async ({ page }) => {
    await openArtifacts(page, RICH, 'IOCs')
    await page.getByRole('button', { name: /^domain/ }).click()
    await expect(page.locator('.artifact-panel:visible tbody tr')).toHaveCount(5)
    await waitForTransitions(page)
    await page.screenshot({ path: screenshotPath('artifacts-iocs-filtered'), fullPage: true })
  })

  test('artifacts-download-tooltip', async ({ page }) => {
    await openArtifacts(page, {}, 'DROPPED')
    await page.locator('a.download-link').first().hover()
    await expect(page.getByRole('tooltip')).toContainText('password: infected')
    await waitForTransitions(page)
    await page.screenshot({ path: screenshotPath('artifacts-download-tooltip') })
  })
})

test('artifacts-not-kept', async ({ page }) => {
  const view = realView<ArtifactsView>('artifacts')
  const body: ArtifactsView = {
    ...view,
    dropped: view.dropped.map((file) => ({ ...file, downloadable: false })),
    procdumps: view.procdumps.map((file) => ({ ...file, downloadable: false })),
  }
  await openArtifacts(page, { artifacts: { body } }, 'DROPPED')
  await expect(page.locator('.artifact-panel:visible .download-unavailable')).toHaveText(['not kept'])
  await expect(page.locator('.artifact-panel:visible .download-note')).toHaveCount(0)
  await page.screenshot({ path: screenshotPath('artifacts-not-kept') })
})

test('artifacts-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 800 })
  await openArtifacts(page, RICH, 'DROPPED')
  await page.screenshot({ path: screenshotPath('artifacts-narrow-600-dropped'), fullPage: true })
  await page.locator('.artifact-sub-tabs').getByRole('tab', { name: /^IOCs/ }).click()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('artifacts-narrow-600-iocs'), fullPage: true })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`artifacts tab does not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openArtifacts(page, RICH)
    for (const tab of SUB_TABS) {
      await page.locator('.artifact-sub-tabs').getByRole('tab', { name: new RegExp(`^${tab}`) }).click()
      await expect(page.locator('.artifact-panel:visible .loader')).toHaveCount(0)
      await expectNoHorizontalOverflow(page)
    }
  })
}
