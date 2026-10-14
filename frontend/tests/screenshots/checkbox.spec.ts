import type { Page } from '@playwright/test'
import {
  GUEST_READY_SYSTEM,
  expect,
  mockRules,
  mockShell,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'
import { SCREENSHOT_RULES, yamlOf } from './rules-data'

const SCALE = 6

async function openRules(page: Page): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockRules(page, { rules: SCREENSHOT_RULES, yaml: yamlOf })
  await page.goto('/rules')
  await expect(page.locator('.rules-table tbody tr').first()).toBeVisible()
  await page.mouse.move(0, 0)
  await waitForTransitions(page)
}

/** Where the dark tick sits inside a checked box, as a fraction of the box from its top-left corner. */
async function tickCentre(page: Page, png: Buffer): Promise<{ x: number; y: number }> {
  return page.evaluate(async (base64) => {
    const image = new Image()
    image.src = `data:image/png;base64,${base64}`
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = image.width
    canvas.height = image.height
    const context = canvas.getContext('2d')!
    context.drawImage(image, 0, 0)
    const { data } = context.getImageData(0, 0, image.width, image.height)
    const inset = Math.round(image.width * 0.25)
    let sumX = 0
    let sumY = 0
    let dark = 0
    for (let y = inset; y < image.height - inset; y++) {
      for (let x = inset; x < image.width - inset; x++) {
        const offset = (y * image.width + x) * 4
        if (data[offset]! < 80 && data[offset + 1]! < 80 && data[offset + 2]! < 80) {
          sumX += x
          sumY += y
          dark++
        }
      }
    }
    return { x: dark ? sumX / dark / image.width : NaN, y: dark ? sumY / dark / image.height : NaN }
  }, png.toString('base64'))
}

test('checkbox-checked-tick-is-centred-in-the-box', async ({ browser }) => {
  const context = await browser.newContext({ deviceScaleFactor: SCALE, viewport: { width: 1280, height: 720 } })
  const page = await context.newPage()
  await openRules(page)
  const checked = page.locator('.rules-table input.checkbox-input:checked').first()
  await expect(checked).toBeVisible()

  const png = await checked.screenshot({ path: screenshotPath('checkbox-checked') })
  const centre = await tickCentre(page, png)

  expect(centre.x, 'the tick is drawn').not.toBeNaN()
  expect(Math.abs(centre.x - 0.5), `tick centre ${centre.x.toFixed(2)} across the box`).toBeLessThan(0.1)
  expect(Math.abs(centre.y - 0.5), `tick centre ${centre.y.toFixed(2)} down the box`).toBeLessThan(0.1)
  await context.close()
})

test('checkbox-states', async ({ browser }) => {
  const context = await browser.newContext({ deviceScaleFactor: SCALE, viewport: { width: 1280, height: 720 } })
  const page = await context.newPage()
  await openRules(page)
  const boxes = page.locator('.rules-table input.checkbox-input')
  await boxes.first().screenshot({ path: screenshotPath('checkbox-state-checked') })
  await boxes.first().hover()
  await boxes.first().screenshot({ path: screenshotPath('checkbox-state-checked-hover') })
  await boxes.first().focus()
  await boxes.first().screenshot({ path: screenshotPath('checkbox-state-checked-focus') })
  await context.close()
})
