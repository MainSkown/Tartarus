import { createMemoryHistory } from 'vue-router'
import { describe, expect, it } from 'vitest'
import { createAppRouter } from '@/router'

describe('router', () => {
  it('resolves the placeholder page at /', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('placeholder')
    expect(router.currentRoute.value.matched).not.toHaveLength(0)
  })

  it('falls back to the placeholder page for unknown paths', () => {
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve('/no/such/page').name).toBe('placeholder')
  })
})
