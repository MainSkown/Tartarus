import { describe, expect, it } from 'vitest'
import RulesPage from '@/pages/RulesPage.vue'
import { routes } from '@/router/routes'

describe('routes', () => {
  it('serves /rules with the Rules page, not the placeholder', async () => {
    const rules = routes[0]!.children!.find((route) => route.path === 'rules')!
    const loaded = await (rules.component as () => Promise<{ default: unknown }>)()
    expect(loaded.default).toBe(RulesPage)
  })
})
