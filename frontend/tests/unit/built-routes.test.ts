import { describe, expect, it } from 'vitest'
import { BUILT_ROUTES } from '@/services/routes'

describe('BUILT_ROUTES', () => {
  it('lists the routes the sandbox implements, leaving out the unconfigured tunnels', () => {
    expect(BUILT_ROUTES).toEqual(['inetsim', 'none', 'drop', 'internet'])
  })
})
