import { expect, mockShell, screenshotPath, test } from './fixtures'

const PLACEHOLDER_ROUTES: { name: string; path: string }[] = [
  { name: 'rules-placeholder', path: '/rules' },
  { name: 'guest-placeholder', path: '/guest' },
  { name: 'not-found', path: '/this-route-does-not-exist' },
]

for (const { name, path } of PLACEHOLDER_ROUTES) {
  test(name, async ({ page }) => {
    await mockShell(page)
    await page.goto(path)
    await expect(page.getByText('> not implemented yet')).toBeVisible()
    await page.screenshot({ path: screenshotPath(name) })
  })
}
