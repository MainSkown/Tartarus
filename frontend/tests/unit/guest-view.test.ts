import { describe, expect, it } from 'vitest'
import type { Guest, GuestProfile } from '@/api'
import { checkSummary, guestActions, guestDeleteConfirmation, kindLabel, resourcesLabel, selfTestOf, systemLabel } from '@/services/guest-view'

function guest(overrides: Partial<Guest> = {}): Guest {
  return { name: 'lab1', state: 'ready', ...overrides }
}

const WINDOWS = { id: 'windows', display_name: 'Windows 11' } as GuestProfile

describe('kindLabel', () => {
  it('says BUILD for a guest built from media', () => {
    expect(kindLabel(guest({ kind: 'build' }))).toBe('BUILD')
  })

  it('names the source of a clone', () => {
    expect(kindLabel(guest({ kind: 'clone', cloned_from: 'lab1' }))).toBe('CLONE OF lab1')
  })

  it('says CLONE when the source is not recorded', () => {
    expect(kindLabel(guest({ kind: 'clone' }))).toBe('CLONE')
  })

  it('says ADOPTED for a guest that existed before the wizard', () => {
    expect(kindLabel(guest({ kind: 'build', adopted: true }))).toBe('ADOPTED')
  })

  it('has no kind for a broken guest', () => {
    expect(kindLabel(guest({ state: 'broken' }))).toBeUndefined()
  })
})

describe('systemLabel', () => {
  it('joins the profile name and the media variant', () => {
    const media = { file: 'w.iso', arch: 'x64', variant: 'Pro' }
    expect(systemLabel(guest({ media }), WINDOWS)).toBe('Windows 11 Pro')
  })

  it('uses the edition name when the media could name it', () => {
    const media = { file: 'w.iso', arch: 'x64', variant: '5' }
    expect(systemLabel(guest({ media }), WINDOWS, 'Windows 11 Pro')).toBe('Windows 11 Pro')
  })

  it('never shows a bare edition index', () => {
    const media = { file: 'w.iso', arch: 'x64', variant: '5' }
    expect(systemLabel(guest({ media }), WINDOWS)).toBe('Windows 11')
  })

  it('falls back to the profile id when the profiles are not loaded', () => {
    expect(systemLabel(guest({ profile: 'windows' }), undefined)).toBe('windows')
  })

  it('has no label for a guest with neither profile nor media', () => {
    expect(systemLabel(guest(), undefined)).toBeUndefined()
  })
})

describe('resourcesLabel', () => {
  it('lists vCPUs, RAM in GB and disk', () => {
    expect(resourcesLabel({ vcpus: 4, ram_mb: 8192, disk_gb: 80 })).toBe('4 vCPUs · 8 GB RAM · 80 GB disk')
  })

  it('uses the singular for one vCPU and MB for a RAM that is not whole GB', () => {
    expect(resourcesLabel({ vcpus: 1, ram_mb: 1536, disk_gb: 64 })).toBe('1 vCPU · 1536 MB RAM · 64 GB disk')
  })
})

describe('selfTestOf', () => {
  it('reads the message and the analysis that ran the test', () => {
    const selftest = { message: 'all signals present', analysis_id: 41, signals: {} }
    expect(selfTestOf(guest({ selftest }))).toEqual({ message: 'all signals present', analysisId: 41 })
  })

  it('has no analysis when the test never got that far', () => {
    const selftest = { message: 'the sample did not run', analysis_id: null }
    expect(selfTestOf(guest({ selftest }))).toEqual({ message: 'the sample did not run', analysisId: undefined })
  })

  it('has nothing for a guest never tested, or a record without a message', () => {
    expect(selfTestOf(guest())).toBeUndefined()
    expect(selfTestOf(guest({ selftest: {} }))).toBeUndefined()
  })
})

describe('checkSummary', () => {
  it('counts the failed checks', () => {
    const probe = (ok: boolean) => ({ id: 'x', ok, message: '' })
    expect(checkSummary([probe(true), probe(true)])).toBe('2 of 2 checks passed')
    expect(checkSummary([probe(true), probe(false)])).toBe('1 of 2 checks passed')
    expect(checkSummary([probe(true)])).toBe('1 of 1 check passed')
  })
})

describe('guestDeleteConfirmation', () => {
  it('names the guest in the title and says what goes with it and what stays', () => {
    const { title, message } = guestDeleteConfirmation('lab1')
    expect(title).toBe('Delete lab1')
    expect(message).toContain('Delete the guest lab1?')
    expect(message).toMatch(/disk.*snapshot/)
    expect(message).toContain('analyses that used it keep their data')
    expect(message).toContain('cannot be undone')
  })
})

describe('guestActions', () => {
  it('offers a ready guest its checks, a clone and a delete', () => {
    expect(guestActions(guest({ state: 'ready', build_id: 'b1' }))).toEqual({ runChecks: true, clone: true, remove: true, viewBuild: false })
  })

  it.each(['building', 'testing'] as const)('offers a %s guest only its build', (state) => {
    expect(guestActions(guest({ state, build_id: 'b1' }))).toEqual({ runChecks: false, clone: false, remove: false, viewBuild: true })
  })

  it('has nothing to show for a build whose id is unknown', () => {
    expect(guestActions(guest({ state: 'building' })).viewBuild).toBe(false)
  })

  it('lets a failed guest be deleted and its build be seen, but not checked or cloned', () => {
    expect(guestActions(guest({ state: 'failed', build_id: 'b2' }))).toEqual({ runChecks: false, clone: false, remove: true, viewBuild: true })
  })

  it('lets a broken guest only be deleted', () => {
    expect(guestActions(guest({ state: 'broken' }))).toEqual({ runChecks: false, clone: false, remove: true, viewBuild: false })
  })
})
