import { expect, makeDetectedAnalysis, mockAnalyses, mockShell, mockViews, realView, test } from './fixtures'

test('the shared view mock serves real responses, a process detail and screenshots', async ({ page }) => {
  await mockShell(page)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: 45 })] })
  await mockViews(page, { registry: { status: 500, body: { error: { code: 'internal_error', message: 'boom' } } } })
  await page.goto('/')

  const get = (path: string) => page.evaluate(async (p) => (await fetch(p)).status, path)
  expect(await get('/api/analyses/45/processes')).toBe(200)
  expect(await get('/api/analyses/45/network')).toBe(200)
  expect(await get('/api/analyses/45/registry')).toBe(500)
  expect(await get('/api/analyses/45/processes/9708')).toBe(200)
  expect(await get('/api/analyses/45/processes/1')).toBe(404)
  expect(await get('/api/analyses/45/artifacts/screenshots/1')).toBe(200)

  const processes = realView<{ roots: { name: string; children: { name: string }[] }[] }>('processes')
  expect(processes.roots[0]!.name).toBe('benign.exe')
  expect(processes.roots[0]!.children[0]!.name).toBe('cmd.exe')
})
