import { readFileSync } from 'node:fs'
import { basename } from 'node:path'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { deleteWhenOver } from './delete-when-over'

const SAMPLE = process.env.E2E_SAMPLE
const REAL_SCREENSHOT = process.env.E2E_DESKTOP_SCREENSHOT
const GUEST = { width: 1280, height: 800 }
const START_BUTTON = { x: 441, y: 775 }
const EMPTY_DESKTOP = { x: 900, y: 120 }
const TIMEOUT_S = 120
const FRAME_SETTLE_MS = 1500

const screen = (page: Page) => page.locator('[data-desktop="screen"]')
const display = (page: Page) => page.locator('.live-desktop__stage > div').first()

// A checksum of the display canvas: it changes whenever the guest repaints something visible.
async function frameChecksum(page: Page): Promise<number> {
  return page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>('[data-desktop="screen"] canvas')!
    const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data
    let sum = 0
    for (let at = 0; at < pixels.length; at += 28) sum = (sum * 31 + pixels[at]! + pixels[at + 1]! * 3 + pixels[at + 2]! * 7) >>> 0
    return sum
  })
}

async function litPixels(page: Page): Promise<number> {
  return page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>('[data-desktop="screen"] canvas')
    if (!canvas || canvas.width === 0 || canvas.height === 0) return 0
    const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data
    let lit = 0
    for (let at = 0; at < pixels.length; at += 4) if (pixels[at]! + pixels[at + 1]! + pixels[at + 2]! > 60) lit += 1
    return lit
  })
}

// The mapping uses the display element, which is exactly the guest's 16:10 scaled; the canvas inside is taller (a whole number of tiles).
async function clickGuest(page: Page, at: { x: number; y: number }): Promise<void> {
  const box = (await display(page).boundingBox())!
  await page.mouse.move(box.x + (at.x / GUEST.width) * box.width, box.y + (at.y / GUEST.height) * box.height)
  await page.mouse.down()
  await page.mouse.up()
}

async function pressAndExpectChange(page: Page, press: () => Promise<void>, message: string): Promise<void> {
  const before = await frameChecksum(page)
  await press()
  await expect.poll(() => frameChecksum(page), { message, timeout: 10_000 }).not.toBe(before)
}

async function submitInteractive(request: APIRequestContext, sample: string): Promise<string> {
  const response = await request.post('/api/analyses', {
    multipart: {
      file: { name: basename(sample), mimeType: 'application/octet-stream', buffer: readFileSync(sample) },
      options: JSON.stringify({ interactive: true, route: 'inetsim', timeout: TIMEOUT_S }),
    },
  })
  expect(response.status()).toBe(201)
  return String((await response.json()).id)
}

// Real stack, a real guest, minutes long: opt in with E2E_DESKTOP=1.
test('the interactive desktop shows the guest, takes the mouse, takes keys only while focused, and ends with the run', async ({
  page,
  request,
}, testInfo) => {
  test.skip(process.env.E2E_DESKTOP !== '1', 'an interactive run lasts its whole timeout; set E2E_DESKTOP=1 to run it')
  test.skip(!SAMPLE, 'E2E_SAMPLE must name the file to submit')
  test.setTimeout(480_000)
  const id = await submitInteractive(request, SAMPLE as string)
  const pageErrors: string[] = []
  const keysSent: string[] = []
  page.on('websocket', (socket) => {
    if (socket.url().endsWith('/desktop')) socket.on('framesent', (frame) => String(frame.payload).startsWith('3.key,') && keysSent.push(String(frame.payload)))
  })
  const shoot = (name: string) => page.screenshot({ path: testInfo.outputPath(`${name}.png`) })
  page.on('pageerror', (error) => pageErrors.push(error.message))

  try {
    await page.goto(`/analyses/${id}`)
    await expect(page.locator('.analysis-tabs [aria-selected="true"]')).toHaveText('LIVE')

    await expect(page.locator('[data-desktop="message"]')).toHaveCount(0, { timeout: 120_000 })
    await expect.poll(() => litPixels(page), { message: 'the display canvas is blank' }).toBeGreaterThan(100_000)
    await page.waitForTimeout(FRAME_SETTLE_MS)
    if (REAL_SCREENSHOT) await page.screenshot({ path: REAL_SCREENSHOT })

    await page.keyboard.press('Meta')
    await page.keyboard.press('a')
    await page.waitForTimeout(FRAME_SETTLE_MS)
    await shoot('1-unfocused-keys')
    expect(keysSent, 'keys reached the guest although the panel had no focus').toEqual([])

    await pressAndExpectChange(page, () => clickGuest(page, START_BUTTON), 'a click on the Start button did not change the guest screen')
    await expect(screen(page)).toHaveAttribute('data-captured', 'true')
    await shoot('2-after-start-click')

    await pressAndExpectChange(page, () => clickGuest(page, EMPTY_DESKTOP), 'the Start menu did not close on a click elsewhere')
    await page.waitForTimeout(FRAME_SETTLE_MS)
    await pressAndExpectChange(page, () => page.keyboard.press('Meta'), 'the Windows key did not change the guest screen while the panel had focus')
    await shoot('3-focused-meta')
    expect(keysSent.length, 'the Windows key was not sent while the panel had focus').toBeGreaterThan(0)
    await page.keyboard.press('Meta')

    await page.keyboard.press('Escape')
    await page.keyboard.press('Escape')
    await expect(screen(page)).toHaveAttribute('data-captured', 'false')

    await expect(page.locator('.status-badge').first()).toContainText(/done/i, { timeout: 300_000 })
    await expect(page.locator('[data-desktop="message"]')).toContainText('The run has ended. CAPE is processing the results.')
    expect(pageErrors).toEqual([])
  } finally {
    await deleteWhenOver(request, id, 360_000)
  }
})
