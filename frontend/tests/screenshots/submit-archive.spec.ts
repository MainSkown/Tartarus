import type { Page } from '@playwright/test'
import type { ArchiveMemberRead, ArchiveMembersRead, ErrorEnvelope, SettingsBody } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  MIXED_ANALYSES,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  mockAnalyses,
  mockSettings,
  mockShell,
  screenshotPath,
  test,
  waitForFieldMessages,
  waitForTransitions,
} from './fixtures'
import { mockGuests } from './guest-data'

test.use({ timezoneId: 'UTC' })

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1100 })
  await mockGuests(page)
})

const STORED_SETTINGS: SettingsBody = {
  default_route: 'inetsim',
  default_timeout: 240,
  default_interactive: true,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}

const ARCHIVE = { name: 'invoice_bundle.zip', mimeType: 'application/zip', buffer: Buffer.concat([Buffer.from('PK\x03\x04'), Buffer.alloc(4096, 7)]) }
const LONG_MEMBER = `payload/stage2/${'quarterly_financial_report_final_FINAL_v2_signed_'.repeat(3)}invoice.pdf.exe`

function member(name: string, overrides: Partial<ArchiveMemberRead> = {}): ArchiveMemberRead {
  return { name, size: 184_320, encrypted: true, unsafe: false, unsupported: false, ...overrides }
}

const ONE_MEMBER: ArchiveMembersRead = { members: [member('invoice.exe', { size: 1_482_752 })], password_ok: true }
const THREE_MEMBERS: ArchiveMembersRead = {
  members: [member('loader.exe', { size: 1_482_752 }), member('helper.dll', { size: 96_256 }), member('config.ini', { size: 312 })],
  password_ok: true,
}
const REFUSED_MEMBERS: ArchiveMembersRead = {
  members: [
    member('loader.exe', { size: 1_482_752 }),
    member('../../Windows/System32/evil.dll', { size: 96_256, unsafe: true }),
    member('C:\\Users\\Public\\drop.exe', { size: 4096, unsafe: true }),
    member('report, final.exe', { size: 52_224, unsupported: true }),
  ],
  password_ok: true,
}
const LONG_NAMES: ArchiveMembersRead = {
  members: [member(LONG_MEMBER, { size: 1_482_752 }), member('a/very/deeply/nested/folder/structure/inside/the/archive/setup.exe'), member('readme.txt', { size: 312 })],
  password_ok: true,
}
const WRONG_PASSWORD: ArchiveMembersRead = { members: THREE_MEMBERS.members, password_ok: false }

interface ArchiveReply {
  status?: number
  body: ArchiveMembersRead | ErrorEnvelope
  gate?: Promise<void>
}

async function mockArchiveMembers(page: Page, reply: ArchiveReply): Promise<void> {
  await page.route(
    (url) => url.pathname === '/api/analyses/archive-members',
    async (route) => {
      await reply.gate
      await route.fulfill({ status: reply.status ?? 200, json: reply.body })
    },
  )
}

async function openSubmitDialog(page: Page): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: STORED_SETTINGS })
  await mockAnalyses(page, { items: MIXED_ANALYSES })
  await page.goto('/')
  await page.getByRole('button', { name: '+ SUBMIT', exact: true }).click()
  await expect(page.getByLabel('TIMEOUT')).toHaveValue('240')
  await waitForTransitions(page)
}

async function chooseArchive(page: Page, file: { name: string; mimeType: string; buffer: Buffer } = ARCHIVE): Promise<void> {
  await page.locator('input[type="file"]').setInputFiles(file)
  await expect(page.locator('.file-hash')).toHaveText(/sha256 [0-9a-f]{64}/)
}

async function shoot(page: Page, name: string): Promise<void> {
  await waitForFieldMessages(page)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name) })
}

test('submit-archive-loading', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await mockArchiveMembers(page, { body: ONE_MEMBER, gate })
  await openSubmitDialog(page)
  await chooseArchive(page)
  await expect(page.locator('.archive-loading')).toBeVisible()
  await expect(page.locator('.submit-reason')).toHaveText('Reading the archive…')
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeDisabled()
  await shoot(page, 'submit-archive-loading')
  release()
})

test('submit-archive-one-member', async ({ page }) => {
  await mockArchiveMembers(page, { body: ONE_MEMBER })
  await openSubmitDialog(page)
  await chooseArchive(page)
  await expect(page.getByRole('radio', { name: /invoice\.exe/ })).toBeChecked()
  await expect(page.getByLabel('ARCHIVE PASSWORD')).toHaveValue('infected')
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeEnabled()
  await shoot(page, 'submit-archive-one-member')
})

test('submit-archive-three-members', async ({ page }) => {
  await mockArchiveMembers(page, { body: THREE_MEMBERS })
  await openSubmitDialog(page)
  await chooseArchive(page)
  await expect(page.getByRole('radiogroup', { name: 'Files in the archive' })).toBeVisible()
  await expect(page.getByRole('radio', { checked: true })).toHaveCount(1)
  await expect(page.locator('.submit-reason')).toHaveText('Choose the file to run from the archive')
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeDisabled()
  await shoot(page, 'submit-archive-three-members')
})

test('submit-archive-member-chosen', async ({ page }) => {
  await mockArchiveMembers(page, { body: THREE_MEMBERS })
  await openSubmitDialog(page)
  await chooseArchive(page)
  await page.getByRole('radio', { name: /helper\.dll/ }).check()
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeEnabled()
  await shoot(page, 'submit-archive-member-chosen')
})

test('submit-archive-wrong-password', async ({ page }) => {
  await mockArchiveMembers(page, { body: WRONG_PASSWORD })
  await openSubmitDialog(page)
  await chooseArchive(page)
  await expect(page.getByText('The password does not open the archive')).toBeVisible()
  await expect(page.locator('.submit-reason')).toHaveText('Enter the password that opens the archive')
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeDisabled()
  await shoot(page, 'submit-archive-wrong-password')
})

test('submit-archive-not-a-zip', async ({ page }) => {
  await mockArchiveMembers(page, { status: 422, body: errorEnvelope('validation_error', 'The file is not a zip archive: its central directory is missing or damaged.') })
  await openSubmitDialog(page)
  await chooseArchive(page, { name: 'notes.zip', mimeType: 'application/zip', buffer: Buffer.from('this is plain text, not a zip') })
  await expect(page.locator('.archive-error')).toHaveText('The file is not a zip archive: its central directory is missing or damaged.')
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeDisabled()
  await shoot(page, 'submit-archive-not-a-zip')
})

test('submit-archive-refused-members', async ({ page }) => {
  await mockArchiveMembers(page, { body: REFUSED_MEMBERS })
  await openSubmitDialog(page)
  await chooseArchive(page)
  await expect(page.getByRole('radio', { name: /evil\.dll/ })).toBeDisabled()
  await expect(page.getByRole('radio', { name: /report, final\.exe/ })).toBeDisabled()
  await expect(page.getByRole('radio', { name: /loader\.exe/ })).toBeChecked()
  await shoot(page, 'submit-archive-refused-members')
})

test('submit-archive-long-names', async ({ page }) => {
  await mockArchiveMembers(page, { body: LONG_NAMES })
  await openSubmitDialog(page)
  await chooseArchive(page, { ...ARCHIVE, name: `${'bundle_of_quarterly_reports_'.repeat(6)}.zip` })
  await page.getByRole('radio', { name: /readme\.txt/ }).check()
  await expectNoHorizontalOverflow(page)
  await shoot(page, 'submit-archive-long-names')
})

test('submit-archive-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 1100 })
  await mockArchiveMembers(page, { body: REFUSED_MEMBERS })
  await openSubmitDialog(page)
  await chooseArchive(page)
  await expectNoHorizontalOverflow(page)
  await shoot(page, 'submit-archive-narrow-600')
})

test('submit-archive-narrow-360-long-names', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 1200 })
  await mockArchiveMembers(page, { body: LONG_NAMES })
  await openSubmitDialog(page)
  await chooseArchive(page)
  await page.getByRole('radio', { name: /readme\.txt/ }).check()
  await expectNoHorizontalOverflow(page)
  await shoot(page, 'submit-archive-narrow-360-long-names')
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`submit archive fields do not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    await mockArchiveMembers(page, { body: LONG_NAMES })
    await openSubmitDialog(page)
    await chooseArchive(page)
    await expect(page.locator('.archive-fields')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    const box = await page.locator('.submit-dialog').boundingBox()
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
  })
}
