import type { Page } from '@playwright/test'
import type { AttackMatrix, AttackTactic, Detection, DetectionsView, RelatedEvent } from '../../src/api/types.gen'
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
  screenshotPath,
  test,
  waitForTransitions,
  type ViewMock,
  type ViewName,
} from './fixtures'

const ID = 45
const BENIGN = { pid: 9708, name: 'benign.exe' }
const EMPTY_DETECTIONS: DetectionsView = { groups: [], total: 0 }
const EMPTY_ATTACK: AttackMatrix = { tactics: [], attack_version: '19.2' }
const LONG_NAME = `suspicious_${'unbroken_rule_name_segment_'.repeat(6)}end`
const LONG_PATH = `C:\\Users\\Administrator\\AppData\\Local\\Temp\\${'nested_directory_'.repeat(8)}payload.exe`
const LONG_REFERENCE = `https://example.com/research/${'a-very-long-report-slug-'.repeat(8)}`

async function openDetections(page: Page, overrides: Partial<Record<ViewName, ViewMock>> = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockViews(page, overrides)
  await page.goto(`/analyses/${ID}/detections`)
}

async function switchToMatrix(page: Page): Promise<void> {
  await page.locator('label.radio-label', { hasText: 'ATT&CK' }).click()
}

async function showMatrix(page: Page): Promise<void> {
  await switchToMatrix(page)
  await expect(page.locator('.attack-matrix')).toBeVisible()
}

function relatedEvents(count: number): RelatedEvent[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `event-${index}`,
    time: `2026-10-13T15:39:${String(10 + index).padStart(2, '0')}.${String(index * 37).padStart(3, '0')}000Z`,
    lane: ['api', 'file', 'registry', 'network', 'process'][index % 5]!,
    action: 'api-call',
    summary: `benign.exe called NtWriteVirtualMemory against ${LONG_PATH.slice(0, 40 + index * 6)}`,
    process: index % 3 === 0 ? { pid: 2476, name: 'cmd.exe' } : BENIGN,
  }))
}

function synthetic(overrides: Partial<Detection> & Pick<Detection, 'id' | 'name' | 'ruleset'>): Detection {
  return {
    description: 'Detects a behaviour that is typical of this kind of sample',
    severity: 'medium',
    techniques: [],
    match: null,
    references: [],
    time: '2026-10-13T15:39:50.753000Z',
    process: BENIGN,
    related_events: [],
    related_event_total: 0,
    ...overrides,
  }
}

const MIXED_RULESETS: DetectionsView = {
  total: 6,
  groups: [
    {
      ruleset: 'cape',
      detections: [
        synthetic({ id: 'c1', name: 'injection_createremotethread', ruleset: 'cape', severity: 'high', techniques: ['T1055'] }),
        synthetic({ id: 'c2', name: 'antivm_checks_available_memory', ruleset: 'cape', severity: 'low' }),
      ],
    },
    {
      ruleset: 'suricata',
      detections: [
        synthetic({
          id: 's1',
          name: 'ET MALWARE Win32/Formbook CnC Checkin (POST)',
          ruleset: 'suricata',
          severity: 'high',
          techniques: ['T1071'],
          process: null,
          description: null,
        }),
      ],
    },
    {
      ruleset: 'yara',
      detections: [synthetic({ id: 'y1', name: 'Formbook_unpacked', ruleset: 'yara', severity: 'critical', techniques: ['T1027'] })],
    },
    {
      ruleset: 'sigma',
      detections: [
        synthetic({
          id: 'g1',
          name: 'proc_creation_win_remote_thread_unusual_target',
          ruleset: 'sigma',
          severity: 'critical',
          description: 'Detects a remote thread created in a process that rarely receives one',
          techniques: ['T1055', 'T1055.003', 'T1055.012'],
          match:
            'selection:\n  EventID: 8\n  TargetImage|endswith:\n    - \\winlogon.exe\n    - \\lsass.exe\nfilter:\n  SourceImage|endswith: \\csrss.exe\ncondition: selection and not filter',
          references: ['https://attack.mitre.org/techniques/T1055/', 'https://github.com/SigmaHQ/sigma/blob/master/rules/windows/create_remote_thread/'],
          related_events: relatedEvents(25),
          related_event_total: 480,
        }),
        synthetic({ id: 'g2', name: 'proc_creation_win_susp_powershell_encoded', ruleset: 'sigma', severity: 'medium', techniques: ['T1059.001'] }),
      ],
    },
  ],
}

const LONG_TEXT: DetectionsView = {
  total: 2,
  groups: [
    {
      ruleset: 'sigma',
      detections: [
        synthetic({
          id: 'long',
          name: LONG_NAME,
          ruleset: 'sigma',
          severity: 'high',
          description: `${'Detects extremely verbose behaviour that keeps going without a pause '.repeat(6)}end`,
          techniques: Array.from({ length: 14 }, (_, index) => `T1${String(index * 7 + 100).padStart(3, '0')}.00${index % 9}`),
          match: `CommandLine|contains: '${'A'.repeat(220)}'\ncondition: selection`,
          references: [LONG_REFERENCE, `not a web address ${LONG_PATH}`],
          process: { pid: 31337, name: `${'a_process_with_a_really_long_image_name_'.repeat(3)}.exe` },
          related_events: relatedEvents(3),
          related_event_total: 3,
        }),
        synthetic({ id: 'short', name: 'short_rule', ruleset: 'sigma', severity: 'low' }),
      ],
    },
  ],
}

function manyTacticsMatrix(): AttackMatrix {
  const names = [
    'Reconnaissance', 'Resource Development', 'Initial Access', 'Execution', 'Persistence', 'Privilege Escalation',
    'Stealth', 'Defense Impairment', 'Credential Access', 'Discovery', 'Lateral Movement', 'Collection',
    'Command and Control', 'Exfiltration', 'Impact',
  ]
  const severities = ['critical', 'high', 'medium', 'low', 'info'] as const
  const tactics: AttackTactic[] = names.map((name, column) => ({
    id: name.toLowerCase().replaceAll(' ', '-'),
    name,
    techniques: Array.from({ length: 1 + (column % 4) }, (_, row) => ({
      id: `T1${String(column * 10 + row).padStart(3, '0')}${row % 2 ? '.001' : ''}`,
      name: row === 2 ? `${'A technique with an extremely long official name '.repeat(2)}` : `Technique ${column}.${row}`,
      hit_count: 1 + ((column * 7 + row * 3) % 12),
      severity: severities[(column + row) % severities.length]!,
      detection_ids: ['x'],
    })),
  }))
  tactics.push({
    id: 'unknown',
    name: 'Unknown',
    techniques: [{ id: 'T1999', name: null, hit_count: 3, severity: 'high', detection_ids: ['x'] }],
  })
  return { tactics, attack_version: '19.2' }
}

test('detections-list', async ({ page }) => {
  await openDetections(page)
  await expect(page.locator('.detection-detail__name')).toBeVisible()
  await page.screenshot({ path: screenshotPath('detections-list'), fullPage: true })
})

test('detections-selected-many-events', async ({ page }) => {
  await openDetections(page)
  await page.locator('.detection-entry', { hasText: 'dllload_suspicious_directory' }).click()
  await expect(page.locator('.related-event')).toHaveCount(10)
  await page.screenshot({ path: screenshotPath('detections-selected-many-events'), fullPage: true })
})

test('detections-mixed-rulesets-capped-events', async ({ page }) => {
  await openDetections(page, { detections: { body: MIXED_RULESETS } })
  await expect(page.locator('.detection-detail__events-count')).toHaveText('25 of 480 shown')
  await page.screenshot({ path: screenshotPath('detections-mixed-rulesets-capped-events'), fullPage: true })
})

test('the detail starts on the same line as the list: both lead with a heading, then the severity badge', async ({ page }) => {
  await openDetections(page)
  await expect(page.locator('.detection-detail')).toBeVisible()
  const tops = await page.evaluate(() => {
    const top = (selector: string) => document.querySelector(selector)!.getBoundingClientRect().top
    return {
      heading: [top('.detection-group .pane-heading'), top('.detection-detail .pane-heading')],
      badge: [top('.detection-entry .severity-badge'), top('.detection-detail .severity-badge')],
    }
  })
  expect(tops.heading[1], 'heading of the detail vs the list').toBeCloseTo(tops.heading[0]!, 0)
  expect(tops.badge[1], 'severity badge of the detail vs the first list entry').toBeCloseTo(tops.badge[0]!, 0)
})

test('detections-matrix', async ({ page }) => {
  await openDetections(page)
  await showMatrix(page)
  await page.screenshot({ path: screenshotPath('detections-matrix'), fullPage: true })
})

test('detections-matrix-many-tactics', async ({ page }) => {
  await openDetections(page, { attack: { body: manyTacticsMatrix() } })
  await showMatrix(page)
  await expect(page.locator('.attack-tactic__name', { hasText: 'Unknown' })).toHaveCount(1)
  await page.screenshot({ path: screenshotPath('detections-matrix-many-tactics'), fullPage: true })
})

test('detections-technique-filter', async ({ page }) => {
  await openDetections(page)
  await showMatrix(page)
  await page.locator('.attack-cell', { hasText: 'T1055' }).first().click()
  await expect(page.locator('.technique-filter')).toContainText('T1055')
  await page.screenshot({ path: screenshotPath('detections-technique-filter'), fullPage: true })
})

test('detections-empty', async ({ page }) => {
  await openDetections(page, { detections: { body: EMPTY_DETECTIONS }, attack: { body: EMPTY_ATTACK } })
  await expect(page.getByText('> no detections')).toBeVisible()
  await page.screenshot({ path: screenshotPath('detections-empty'), fullPage: true })
})

test('detections-matrix-empty', async ({ page }) => {
  await openDetections(page, { attack: { body: EMPTY_ATTACK } })
  await switchToMatrix(page)
  await expect(page.getByText('> no ATT&CK techniques were raised')).toBeVisible()
  await page.screenshot({ path: screenshotPath('detections-matrix-empty'), fullPage: true })
})

test('detections-error', async ({ page }) => {
  await openDetections(page, {
    detections: { status: 500, body: errorEnvelope('internal_error', 'OpenSearch is unreachable') },
  })
  await expect(page.getByText('failed to load: OpenSearch is unreachable')).toBeVisible()
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await page.screenshot({ path: screenshotPath('detections-error'), fullPage: true })
})

test('detections-loading', async ({ page }) => {
  await openDetections(page, { detections: { delayMs: 3000 } })
  await expect(page.locator('.loader')).toBeVisible()
  await page.screenshot({ path: screenshotPath('detections-loading') })
})

test('detections-long-text', async ({ page }) => {
  await openDetections(page, { detections: { body: LONG_TEXT } })
  await expect(page.locator('.detection-detail__name')).toContainText('suspicious_')
  await page.screenshot({ path: screenshotPath('detections-long-text'), fullPage: true })
})

test('detections-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  await openDetections(page, { detections: { body: MIXED_RULESETS } })
  await expect(page.locator('.detection-detail__name')).toBeVisible()
  await page.screenshot({ path: screenshotPath('detections-narrow-600'), fullPage: true })
})

test('detections-matrix-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  await openDetections(page)
  await showMatrix(page)
  await page.screenshot({ path: screenshotPath('detections-matrix-narrow-600'), fullPage: true })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`detections tab does not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openDetections(page, { detections: { body: LONG_TEXT }, attack: { body: manyTacticsMatrix() } })
    await expect(page.locator('.detection-detail__name')).toBeVisible()
    await waitForTransitions(page)
    await expectNoHorizontalOverflow(page)
    await showMatrix(page)
    await expectNoHorizontalOverflow(page)
  })
}
