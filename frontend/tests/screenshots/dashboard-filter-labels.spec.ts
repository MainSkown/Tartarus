import { GUEST_READY_SYSTEM, MIXED_ANALYSES, expect, mockAnalyses, mockShell, test } from './fixtures'

test('an unfloated filter label is vertically centred in its field', async ({ page }) => {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: MIXED_ANALYSES })
  await page.goto('/')
  const labels = page.locator('.dashboard-filters .q-field__label')
  await expect(labels).toHaveCount(2)

  const offsets = await labels.evaluateAll((elements) =>
    elements.map((label) => {
      const labelBox = label.getBoundingClientRect()
      const controlBox = (label.closest('.q-field__control') as HTMLElement).getBoundingClientRect()
      return (labelBox.top + labelBox.bottom) / 2 - (controlBox.top + controlBox.bottom) / 2
    }),
  )

  expect(offsets).toEqual([0, 0])
})
