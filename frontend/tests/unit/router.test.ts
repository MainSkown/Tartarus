import { createMemoryHistory } from 'vue-router'
import { describe, expect, it } from 'vitest'
import { createAppRouter } from '@/router'

describe('router', () => {
  it.each([
    ['/', 'dashboard'],
    ['/rules', 'rules'],
    ['/guest', 'guest'],
    ['/settings', 'settings'],
    ['/analyses/42', 'analysis-workspace'],
    ['/analyses/42/events', 'analysis-workspace'],
  ])('resolves %s to the %s route, nested under the app shell layout', (path, name) => {
    const router = createAppRouter(createMemoryHistory())
    const resolved = router.resolve(path)
    expect(resolved.name).toBe(name)
    // More than one matched record means it's a child of the shell layout route, not top-level.
    expect(resolved.matched.length).toBeGreaterThan(1)
  })

  it('falls back to the not-found route for unknown paths, still nested under the shell', () => {
    const router = createAppRouter(createMemoryHistory())
    const resolved = router.resolve('/no/such/page')
    expect(resolved.name).toBe('not-found')
    expect(resolved.matched.length).toBeGreaterThan(1)
  })

  it('reads :id and the optional :tab separately on the analysis workspace route', () => {
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve('/analyses/42').params).toMatchObject({ id: '42' })
    expect(router.resolve('/analyses/42/events').params).toMatchObject({ id: '42', tab: 'events' })
  })
})
