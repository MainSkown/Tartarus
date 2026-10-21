import { GUEST_READY_SYSTEM, expect, mockAnalyses, mockSettings, mockShell, test } from './fixtures'
import { mockGuests } from './guest-data'

test('the health dots share one baseline, the Guest trigger button included', async ({ page }) => {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: {} })
  await mockAnalyses(page, { items: [] })
  await mockGuests(page, {})
  await page.goto('/')
  await expect(page.locator('.health-dot')).toHaveCount(3)

  const tops = await page.locator('.health-dot').evaluateAll((dots) => dots.map((dot) => dot.getBoundingClientRect().top))

  expect(new Set(tops).size).toBe(1)
})
