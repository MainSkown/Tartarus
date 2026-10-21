import type { Page } from '@playwright/test'
import type { SettingsBody } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  MIXED_ANALYSES,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeAnalysis,
  mockAnalyses,
  mockSettings,
  mockShell,
  screenshotPath,
  test,
  waitForFieldMessages,
  waitForTransitions,
  type AnalysesMockOptions,
} from './fixtures'
import {
  MEMORY_IMAGE_FILE,
  OVERSIZED_CAPTURE_FILE,
  OVERSIZED_MEMORY_IMAGE_FILE,
  PCAPNG_LONG_NAME_FILE,
  PCAP_FILE,
  UNSUPPORTED_FILE,
  type ImportFixture,
} from './import-tab-data'
import { mockGuests } from './guest-data'

test.use({ timezoneId: 'UTC' })

test.beforeEach(async ({ page }) => {
  await mockGuests(page)
})

const STORED_SETTINGS: SettingsBody = {
  default_route: 'inetsim',
  default_timeout: 240,
  default_interactive: true,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}

const IMPORT_URL = (url: URL): boolean => url.pathname === '/api/analyses/import'
const MEMORY_IMAGE_URL = (url: URL): boolean => url.pathname === '/api/analyses/import/memory-image'
const IMPORT_BUTTON = /IMPORT/
const TOO_LARGE_413 = 'The backend refused the file: it is over the size limit.'
const UNSUPPORTED_415 = 'The backend does not accept this file type.'

async function openImportTab(page: Page, analyses: Partial<AnalysesMockOptions> = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: STORED_SETTINGS })
  await mockAnalyses(page, { items: MIXED_ANALYSES, ...analyses })
  await page.goto('/')
  await page.getByRole('button', { name: '+ SUBMIT', exact: true }).click()
  await expect(page.getByLabel('TIMEOUT')).toHaveValue('240')
  await page.getByRole('tab', { name: 'Import', exact: true }).click()
  await expect(page.locator('.import-pane')).toBeVisible()
  await waitForTransitions(page)
}

function importButton(page: Page) {
  return page.getByRole('button', { name: IMPORT_BUTTON })
}

/** Picks a file through the input; a `reportedSize` is faked on the File so no large buffer is allocated. */
async function chooseFile(page: Page, file: ImportFixture): Promise<void> {
  const input = page.locator('input.import-file-input')
  if (file.reportedSize === undefined) {
    await input.setInputFiles({ name: file.name, mimeType: 'application/octet-stream', buffer: file.head })
  } else {
    await page.evaluate(
      ({ name, head, size }) => {
        const chosen = new File([new Uint8Array(head)], name, { type: 'application/octet-stream' })
        Object.defineProperty(chosen, 'size', { value: size })
        const transfer = new DataTransfer()
        transfer.items.add(chosen)
        const element = document.querySelector<HTMLInputElement>('input.import-file-input')!
        element.files = transfer.files
        element.dispatchEvent(new Event('change', { bubbles: true }))
      },
      { name: file.name, head: [...file.head], size: file.reportedSize },
    )
  }
  await expect(page.locator('.file-name')).toHaveText(file.name)
}

async function expectKindLabel(page: Page, label: string): Promise<void> {
  await expect(page.locator('.import-kind')).toHaveText(label)
}

async function expectImportError(page: Page, message: string): Promise<void> {
  await expect(page.locator('.import-error')).toHaveText(message)
}

async function captureAt(page: Page, name: string): Promise<void> {
  await waitForFieldMessages(page)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name) })
}

test('import-tab-sample-unchanged', async ({ page }) => {
  await openImportTab(page)
  await chooseFile(page, PCAP_FILE)
  await expectKindLabel(page, 'PCAP capture')
  await page.getByRole('tab', { name: 'Sample', exact: true }).click()
  await expect(page.locator('.submit-reason')).toHaveText('Choose a sample to analyse')
  await expect(page.locator('.file-hash')).toHaveCount(0)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('import-tab-sample-unchanged') })
})

test('import-tab-empty', async ({ page }) => {
  await openImportTab(page)
  await expect(page.locator('.import-reason')).toHaveText('Choose a capture or memory image to import')
  await expect(importButton(page)).toBeDisabled()
  await captureAt(page, 'import-tab-empty')
})

test('import-tab-pcap-chosen', async ({ page }) => {
  await openImportTab(page)
  await chooseFile(page, PCAP_FILE)
  await expectKindLabel(page, 'PCAP capture')
  await expect(page.locator('.file-size')).toBeVisible()
  await expect(importButton(page)).toBeEnabled()
  await captureAt(page, 'import-tab-pcap-chosen')
})

test('import-tab-memory-image-chosen', async ({ page }) => {
  await openImportTab(page)
  await chooseFile(page, MEMORY_IMAGE_FILE)
  await expectKindLabel(page, 'Memory image')
  await expect(page.locator('.import-memory-note')).toContainText('Windows 10 and 11 images only.')
  await expect(importButton(page)).toBeEnabled()
  await captureAt(page, 'import-tab-memory-image-chosen')
})

test('import-tab-unsupported-file', async ({ page }) => {
  await openImportTab(page)
  await chooseFile(page, UNSUPPORTED_FILE)
  await expectImportError(page, 'Not a PCAP capture or a memory image')
  await expect(importButton(page)).toBeDisabled()
  await captureAt(page, 'import-tab-unsupported-file')
})

test('import-tab-capture-too-large', async ({ page }) => {
  await openImportTab(page)
  await chooseFile(page, OVERSIZED_CAPTURE_FILE)
  await expectImportError(page, 'This file is larger than the 512 MB limit for its kind.')
  await expect(importButton(page)).toBeDisabled()
  await captureAt(page, 'import-tab-capture-too-large')
})

test('import-tab-memory-image-too-large', async ({ page }) => {
  await openImportTab(page)
  await chooseFile(page, OVERSIZED_MEMORY_IMAGE_FILE)
  await expectImportError(page, 'This file is larger than the 5 GB limit for its kind.')
  await expect(importButton(page)).toBeDisabled()
  await captureAt(page, 'import-tab-memory-image-too-large')
})

test('import-tab-uploading', async ({ page }) => {
  await openImportTab(page, {})
  await page.route(IMPORT_URL, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 5000))
    await route.fulfill({ status: 201, json: makeAnalysis({ id: 20, filename: PCAP_FILE.name }) })
  })
  await chooseFile(page, PCAP_FILE)
  await importButton(page).click()
  await expect(page.locator('.import-progress')).toHaveText(/Uploading \d+%/)
  await expect(page.locator('.import-progress-bar')).toBeVisible()
  await captureAt(page, 'import-tab-uploading')
})

test('import-tab-413-error', async ({ page }) => {
  await openImportTab(page)
  await page.route(IMPORT_URL, (route) =>
    route.fulfill({ status: 413, json: errorEnvelope('payload_too_large', 'request body too large') }),
  )
  await chooseFile(page, PCAP_FILE)
  await importButton(page).click()
  await expectImportError(page, TOO_LARGE_413)
  await expect(page.locator('.error-banner')).toHaveCount(0)
  await captureAt(page, 'import-tab-413-error')
})

test('import-tab-415-error', async ({ page }) => {
  await openImportTab(page)
  await page.route(MEMORY_IMAGE_URL, (route) =>
    route.fulfill({ status: 415, json: errorEnvelope('unsupported_media_type', 'not a memory image') }),
  )
  await chooseFile(page, MEMORY_IMAGE_FILE)
  await importButton(page).click()
  await expectImportError(page, UNSUPPORTED_415)
  await expect(page.locator('.error-banner')).toHaveCount(0)
  await captureAt(page, 'import-tab-415-error')
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`import-tab-long-filename-at-${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openImportTab(page)
    await chooseFile(page, PCAPNG_LONG_NAME_FILE)
    await expectKindLabel(page, 'PCAP capture')
    await expectNoHorizontalOverflow(page)
    const box = await page.locator('.submit-dialog').boundingBox()
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await captureAt(page, `import-tab-long-filename-at-${width}px`)
  })

  test(`import-tab-memory-image-at-${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openImportTab(page)
    await chooseFile(page, { ...MEMORY_IMAGE_FILE, name: PCAPNG_LONG_NAME_FILE.name })
    await expect(page.locator('.import-memory-note')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    const box = await page.locator('.submit-dialog').boundingBox()
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await captureAt(page, `import-tab-memory-image-at-${width}px`)
  })
}
