import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { failed, succeeded } from './annotation-fixtures'
import { guestFixture } from './guest-fixtures'
import { windowsProfile } from './guest-wizard-fixtures'

const api = vi.hoisted(() => ({
  guestsProfiles: vi.fn(),
  guestsList: vi.fn(),
  guestsClone: vi.fn(),
}))
const push = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => api)
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const { useGuestClone } = await import('@/composables/use-guest-clone')

const STARTED = { job_id: 9, build_id: 'b-lab6', guest: 'lab6' }
// Built with Defender off and decoys on, so the source's values differ from the profile defaults.
const LAB1 = guestFixture({
  options: { defender: false, decoys: true, sysmon: false, key: '', keyboard: 'US' },
  resources: { vcpus: 4, ram_mb: 8192, disk_gb: 100 },
})

function refused(fields: { field: string; message: string }[]) {
  return failed('Request validation failed', 422, {
    fields: fields.map(({ field, message }) => ({ location: ['body', field], message, type: 'rejected' })),
  })
}

async function loadedClone(source = 'lab1') {
  const clone = useGuestClone(source)
  await clone.load()
  return clone
}

beforeEach(() => {
  setActivePinia(createPinia())
  push.mockReset()
  api.guestsList.mockReset().mockResolvedValue(succeeded([LAB1, guestFixture({ name: 'lab4', state: 'building' })]))
  api.guestsProfiles.mockReset().mockResolvedValue(succeeded([windowsProfile()]))
  api.guestsClone.mockReset().mockResolvedValue(succeeded(STARTED))
})

describe('the source guest', () => {
  it('is loading until the lists have answered, then ready', async () => {
    const clone = useGuestClone('lab1')
    expect(clone.status.value).toBe('loading')
    await clone.load()
    expect(clone.status.value).toBe('ready')
    expect(clone.source.value?.name).toBe('lab1')
    expect(clone.profile.value?.id).toBe('windows')
  })

  it('is unknown when no guest has that name', async () => {
    expect((await loadedClone('nobody')).status.value).toBe('unknown')
  })

  it('is not ready while the guest builds, and says its state', async () => {
    const clone = await loadedClone('lab4')
    expect(clone.status.value).toBe('not-ready')
    expect(clone.source.value?.state).toBe('building')
  })

  it('fails when the guest list cannot be read', async () => {
    api.guestsList.mockResolvedValue(failed('The guest control service is not reachable', 502))
    const clone = await loadedClone()
    expect(clone.status.value).toBe('failed')
    expect(clone.loadError.value).toBe('The guest control service is not reachable')
  })

  it('fails when the profile of the guest is not installed', async () => {
    api.guestsProfiles.mockResolvedValue(succeeded([]))
    const clone = await loadedClone()
    expect(clone.status.value).toBe('failed')
    expect(clone.loadError.value).toBe('The profile windows of lab1 is not installed')
  })
})

describe('the starting values', () => {
  it("are the source's current options, not the profile defaults", async () => {
    const clone = await loadedClone()
    expect(clone.options.value).toEqual({ defender: false, decoys: true, sysmon: false, key: '', keyboard: 'US' })
  })

  it("are the source's resources", async () => {
    const clone = await loadedClone()
    expect(clone.resources.value).toEqual({ vcpus: 4, ram_mb: 8192, disk_gb: 100 })
  })

  it('leave the new name and the computer name empty', async () => {
    const clone = await loadedClone()
    expect(clone.name.value).toBe('')
    expect(clone.machine.value).toBe('')
  })

  it('lock every option the profile does not let a clone change', async () => {
    const clone = await loadedClone()
    expect(clone.optionRows.value.map(({ option, locked }) => [option.key, locked])).toEqual([
      ['defender', false],
      ['decoys', false],
      ['sysmon', true],
      ['key', true],
      ['keyboard', true],
    ])
  })

  it('fill an option the source does not record from the profile default', async () => {
    api.guestsList.mockResolvedValue(succeeded([guestFixture({ options: { defender: false } })]))
    const clone = await loadedClone()
    expect(clone.options.value).toMatchObject({ defender: false, decoys: false, keyboard: 'Polish (Programmers)' })
  })
})

describe('the request body', () => {
  it('has the new name, the options a clone may change, the resources it may change and no disk', async () => {
    const clone = await loadedClone()
    clone.name.value = 'lab6'
    clone.setOption('defender', true)
    clone.resources.value = { ...clone.resources.value, vcpus: 2, ram_mb: 4096 }
    expect(clone.body.value).toEqual({
      name: 'lab6',
      options: { defender: true, decoys: true },
      identity: {},
      resources: { vcpus: 2, ram_mb: 4096 },
    })
  })

  it('never sends the username or the password, which a clone inherits', async () => {
    const clone = await loadedClone()
    expect(clone.body.value.identity).not.toHaveProperty('account')
    expect(clone.body.value.identity).not.toHaveProperty('password')
  })

  it('leaves a blank computer name out so the clone gets a random one', async () => {
    const clone = await loadedClone()
    clone.machine.value = '  '
    expect(clone.body.value.identity).toEqual({})
    clone.machine.value = 'LAPTOP-0000001'
    expect(clone.body.value.identity).toEqual({ machine: 'LAPTOP-0000001' })
  })

  it('does not offer a computer name when the profile always generates one', async () => {
    api.guestsProfiles.mockResolvedValue(succeeded([windowsProfile({ clone: { computer_name_editable: false } })]))
    const clone = await loadedClone()
    clone.machine.value = 'LAPTOP-0000001'
    expect(clone.machineEditable.value).toBe(false)
    expect(clone.body.value.identity).toEqual({})
  })
})

describe('validation', () => {
  it('cannot be submitted without a valid new name', async () => {
    const clone = await loadedClone()
    expect(clone.canSubmit.value).toBe(false)
    clone.name.value = 'Bad Name'
    expect(clone.canSubmit.value).toBe(false)
    expect(clone.problems.value.name).toMatch(/lower-case letters/)
    clone.name.value = 'lab6'
    expect(clone.canSubmit.value).toBe(true)
  })

  it('refuses the name of an existing guest', async () => {
    const clone = await loadedClone()
    clone.name.value = 'lab1'
    expect(clone.problems.value.name).toBe('Another guest is already called lab1')
  })

  it('refuses a computer name that breaks the profile pattern', async () => {
    const clone = await loadedClone()
    clone.name.value = 'lab6'
    clone.machine.value = '-bad-'
    expect(clone.problems.value['identity.machine']).toMatch(/^Computer name must match/)
    expect(clone.canSubmit.value).toBe(false)
  })

  it('does not check the disk, which a clone cannot change', async () => {
    api.guestsList.mockResolvedValue(succeeded([guestFixture({ resources: { vcpus: 2, ram_mb: 4096, disk_gb: 40 } })]))
    const clone = await loadedClone()
    clone.name.value = 'lab6'
    expect(clone.problems.value['resources.disk_gb']).toBeUndefined()
    expect(clone.canSubmit.value).toBe(true)
  })
})

describe('submitting', () => {
  async function ready() {
    const clone = await loadedClone()
    clone.name.value = 'lab6'
    return clone
  }

  it('clones the source by its name and goes to the build page', async () => {
    const clone = await ready()
    await clone.submit()
    expect(api.guestsClone).toHaveBeenCalledWith(expect.objectContaining({ path: { name: 'lab1' }, body: clone.body.value }))
    expect(push).toHaveBeenCalledWith('/guest/builds/b-lab6')
  })

  it('does not send an invalid form', async () => {
    const clone = await loadedClone()
    await clone.submit()
    expect(api.guestsClone).not.toHaveBeenCalled()
  })

  it('shows a refusal of the computer name on that field', async () => {
    api.guestsClone.mockResolvedValue(
      refused([{ field: 'identity.machine', message: "contains 'test', which tells a sample what the machine is" }]),
    )
    const clone = await ready()
    await clone.submit()
    expect(clone.errors.value['identity.machine']).toMatch(/contains 'test'/)
    expect(push).not.toHaveBeenCalled()
  })

  it('shows a refusal of a locked option in the banner, since it has no editable input', async () => {
    api.guestsClone.mockResolvedValue(refused([{ field: 'options.sysmon', message: 'cannot be changed on a clone' }]))
    const clone = await ready()
    await clone.submit()
    expect(clone.submission.banner.value).toBe('options.sysmon cannot be changed on a clone')
  })

  it('shows a conflict in the banner', async () => {
    api.guestsClone.mockResolvedValue(failed('Another guest is being built: lab4', 409))
    const clone = await ready()
    await clone.submit()
    expect(clone.submission.banner.value).toBe('Another guest is being built: lab4')
  })

  it('removes the server message from the name once it is edited', async () => {
    api.guestsClone.mockResolvedValue(refused([{ field: 'name', message: 'is reserved' }]))
    const clone = await ready()
    await clone.submit()
    expect(clone.errors.value.name).toBe('is reserved')
    clone.name.value = 'lab7'
    expect(clone.errors.value.name).toBeUndefined()
  })
})
