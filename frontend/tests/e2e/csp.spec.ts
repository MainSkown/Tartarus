import { expect, test, type Page } from '@playwright/test'

const ANALYSIS_ID = process.env.E2E_ANALYSIS_ID
const SETTLE_MS = 750
const ROUTES = ['/', '/rules', '/search', '/guest', '/guest/new', '/settings', '/no-such-page']

interface Violation {
  directive: string
  blocked: string
  source: string
}

async function recordViolations(page: Page): Promise<() => Promise<Violation[]>> {
  await page.addInitScript(() => {
    const seen: Violation[] = []
    ;(window as unknown as { __cspViolations: Violation[] }).__cspViolations = seen
    document.addEventListener('securitypolicyviolation', (event: SecurityPolicyViolationEvent) => {
      seen.push({ directive: event.effectiveDirective, blocked: event.blockedURI, source: `${event.sourceFile}:${event.lineNumber}` })
    })
  })
  return () => page.evaluate(() => (window as unknown as { __cspViolations: Violation[] }).__cspViolations)
}

async function visit(page: Page, path: string): Promise<void> {
  await page.goto(path)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(SETTLE_MS)
}

test('the served policy does not let a style element or stylesheet run inline', async ({ request }) => {
  const response = await request.get('/')
  const policy = response.headers()['content-security-policy'] ?? ''
  const styleSrc = policy.split(';').map((directive) => directive.trim()).find((directive) => directive.startsWith('style-src ')) ?? ''
  expect(styleSrc, `style-src in "${policy}"`).not.toContain("'unsafe-inline'")
  expect(policy).toContain("style-src-attr 'unsafe-inline'")
})

for (const path of ROUTES) {
  test(`${path} raises no policy violation`, async ({ page }) => {
    const violations = await recordViolations(page)
    await visit(page, path)
    expect(await violations()).toEqual([])
  })
}

test('every tab of an analysis raises no policy violation', async ({ page }) => {
  test.skip(!ANALYSIS_ID, 'E2E_ANALYSIS_ID names a finished analysis')
  const violations = await recordViolations(page)
  await visit(page, `/analyses/${ANALYSIS_ID}`)
  const tabs = page.getByRole('tab')
  const count = await tabs.count()
  expect(count).toBeGreaterThan(1)
  for (let index = 0; index < count; index += 1) {
    await tabs.nth(index).click()
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(SETTLE_MS)
  }
  expect(await violations()).toEqual([])
})
