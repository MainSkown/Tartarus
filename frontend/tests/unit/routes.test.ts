import { describe, expect, it } from 'vitest'
import GuestBuildPage from '@/pages/GuestBuildPage.vue'
import GuestClonePage from '@/pages/GuestClonePage.vue'
import GuestPage from '@/pages/GuestPage.vue'
import GuestWizardPage from '@/pages/GuestWizardPage.vue'
import RulesPage from '@/pages/RulesPage.vue'
import { routes } from '@/router/routes'

describe('routes', () => {
  it('serves /rules with the Rules page, not the placeholder', async () => {
    const rules = routes[0]!.children!.find((route) => route.path === 'rules')!
    const loaded = await (rules.component as () => Promise<{ default: unknown }>)()
    expect(loaded.default).toBe(RulesPage)
  })

  const guestRoutes = [
    { path: 'guest', component: GuestPage },
    { path: 'guest/new', component: GuestWizardPage },
    { path: 'guest/clone/:name', component: GuestClonePage },
    { path: 'guest/builds/:buildId', component: GuestBuildPage },
  ]

  it.each(guestRoutes)('serves /$path with the page its task has built so far', async ({ path, component }) => {
    const route = routes[0]!.children!.find((child) => child.path === path)!
    const loaded = await (route.component as () => Promise<{ default: unknown }>)()
    expect(loaded.default).toBe(component)
  })
})
