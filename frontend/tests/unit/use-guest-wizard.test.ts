import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Guest } from '@/api'
import { failed, succeeded } from './annotation-fixtures'
import { BROKEN_MEDIA, mediaEntry, windowsProfile } from './guest-wizard-fixtures'

const api = vi.hoisted(() => ({
  guestsMedia: vi.fn(),
  guestsProfiles: vi.fn(),
  guestsList: vi.fn(),
  guestsStartBuild: vi.fn(),
}))
const push = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => api)
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const { useGuestWizard, stepOfField } = await import('@/composables/use-guest-wizard')

const WIN11 = mediaEntry()
const OTHER_PROFILE_MEDIA = mediaEntry({ file: 'ubuntu.iso', profile: 'ubuntu' })
const STARTED = { job_id: 7, build_id: 'b-lab5', guest: 'lab5' }

function refused(fields: { field: string; message: string }[]) {
  return failed('Request validation failed', 422, {
    fields: fields.map(({ field, message }) => ({ location: ['body', field], message, type: 'rejected' })),
  })
}

async function loadedWizard() {
  const wizard = useGuestWizard()
  await wizard.load()
  return wizard
}

async function atSettings() {
  const wizard = await loadedWizard()
  wizard.selectMedia(WIN11.file)
  wizard.next()
  wizard.name.value = 'lab5'
  return wizard
}

beforeEach(() => {
  setActivePinia(createPinia())
  push.mockReset()
  api.guestsMedia.mockReset().mockResolvedValue(succeeded([WIN11, BROKEN_MEDIA, OTHER_PROFILE_MEDIA]))
  api.guestsProfiles.mockReset().mockResolvedValue(succeeded([windowsProfile()]))
  api.guestsList.mockReset().mockResolvedValue(succeeded([{ name: 'lab1', state: 'ready' } as Guest]))
  api.guestsStartBuild.mockReset().mockResolvedValue(succeeded(STARTED))
})

describe('loading the media', () => {
  it('is loading until the lists have answered, then loaded', async () => {
    const wizard = useGuestWizard()
    expect(wizard.mediaStatus.value).toBe('loading')
    await wizard.load()
    expect(wizard.mediaStatus.value).toBe('loaded')
  })

  it('offers an image a profile recognised and disables the ones it cannot build from, with the reason', async () => {
    const wizard = await loadedWizard()
    expect(wizard.mediaChoices.value.map((choice) => [choice.entry.file, choice.profileName, choice.unavailable])).toEqual([
      [WIN11.file, 'Windows', undefined],
      ['notes.iso', undefined, BROKEN_MEDIA.error],
      ['ubuntu.iso', undefined, 'No installed profile reads this image (ubuntu)'],
    ])
  })

  it('fails with the server message and recovers on the next load', async () => {
    api.guestsMedia.mockResolvedValueOnce(failed('The guest control service is not reachable', 502))
    const wizard = await loadedWizard()
    expect(wizard.mediaStatus.value).toBe('failed')
    expect(wizard.mediaError.value).toBe('The guest control service is not reachable')
    await wizard.load()
    expect(wizard.mediaStatus.value).toBe('loaded')
  })

  it('has an empty list when no image is in data/iso', async () => {
    api.guestsMedia.mockResolvedValue(succeeded([]))
    const wizard = await loadedWizard()
    expect(wizard.mediaStatus.value).toBe('loaded')
    expect(wizard.mediaChoices.value).toEqual([])
  })
})

describe('step 1, choosing the media', () => {
  it('cannot continue until an image is chosen', async () => {
    const wizard = await loadedWizard()
    expect(wizard.canContinue.value).toBe(false)
    wizard.next()
    expect(wizard.step.value).toBe(1)
    wizard.selectMedia(WIN11.file)
    expect(wizard.canContinue.value).toBe(true)
    wizard.next()
    expect(wizard.step.value).toBe(2)
  })

  it('does not choose an image that is not available', async () => {
    const wizard = await loadedWizard()
    wizard.selectMedia('notes.iso')
    wizard.selectMedia('ubuntu.iso')
    expect(wizard.selectedMedia.value).toBeUndefined()
  })

  it('takes the profile of the chosen image and preselects its first edition', async () => {
    const wizard = await loadedWizard()
    wizard.selectMedia(WIN11.file)
    expect(wizard.profile.value?.id).toBe('windows')
    expect(wizard.variantIndex.value).toBe(1)
    expect(wizard.variantChoices.value).toEqual([
      { value: 1, label: 'Windows 11 Home · pl-PL' },
      { value: 5, label: 'Windows 11 Pro · pl-PL' },
    ])
  })

  it('starts the settings from the profile defaults', async () => {
    const wizard = await loadedWizard()
    wizard.selectMedia(WIN11.file)
    expect(wizard.options.value).toMatchObject({ defender: true, decoys: false, keyboard: 'Polish (Programmers)' })
    expect(wizard.resources.value).toEqual({ vcpus: 2, ram_mb: 4096, disk_gb: 80 })
  })

  it('keeps the settings when the same image is chosen again, and starts over for another', async () => {
    api.guestsMedia.mockResolvedValue(succeeded([WIN11, mediaEntry({ file: 'other.iso' })]))
    const wizard = await loadedWizard()
    wizard.selectMedia(WIN11.file)
    wizard.setOption('defender', false)
    wizard.selectMedia(WIN11.file)
    expect(wizard.options.value.defender).toBe(false)
    wizard.selectMedia('other.iso')
    expect(wizard.options.value.defender).toBe(true)
  })

  it('goes back to an earlier step and not forward past the one that is open', async () => {
    const wizard = await atSettings()
    wizard.back()
    expect(wizard.step.value).toBe(1)
    wizard.goTo(3)
    expect(wizard.step.value).toBe(1)
    wizard.next()
    wizard.goTo(1)
    expect(wizard.step.value).toBe(1)
  })
})

describe('step 2, the settings', () => {
  it('cannot continue without a valid guest name', async () => {
    const wizard = await atSettings()
    wizard.name.value = ''
    expect(wizard.canContinue.value).toBe(false)
    wizard.name.value = 'Bad Name'
    expect(wizard.canContinue.value).toBe(false)
    expect(wizard.problems.value.name).toMatch(/lower-case letters/)
    wizard.name.value = 'lab5'
    expect(wizard.canContinue.value).toBe(true)
  })

  it('says nothing about a name that is still empty', async () => {
    const wizard = await atSettings()
    wizard.name.value = ''
    expect(wizard.problems.value.name).toBeUndefined()
  })

  it('refuses a name another guest has', async () => {
    const wizard = await atSettings()
    wizard.name.value = 'lab1'
    expect(wizard.problems.value.name).toBe('Another guest is already called lab1')
    expect(wizard.canContinue.value).toBe(false)
  })

  it('blocks on a typed username that breaks the profile pattern but not on a blank one', async () => {
    const wizard = await atSettings()
    expect(wizard.canContinue.value).toBe(true)
    wizard.account.value = 'two words'
    expect(wizard.problems.value['identity.account']).toMatch(/^Username must match/)
    expect(wizard.canContinue.value).toBe(false)
    wizard.account.value = ''
    expect(wizard.canContinue.value).toBe(true)
  })

  it('blocks on a disk under the profile minimum', async () => {
    const wizard = await atSettings()
    wizard.resources.value = { ...wizard.resources.value, disk_gb: 40 }
    expect(wizard.problems.value['resources.disk_gb']).toBe('At least 64 GB')
    expect(wizard.canContinue.value).toBe(false)
  })

  it('moves to the review when the settings are valid', async () => {
    const wizard = await atSettings()
    wizard.next()
    expect(wizard.step.value).toBe(3)
  })

  it('leaves out the edition when the medium lists none', async () => {
    api.guestsMedia.mockResolvedValue(succeeded([mediaEntry({ variants: [] })]))
    const wizard = await loadedWizard()
    wizard.selectMedia(WIN11.file)
    expect(wizard.variantChoices.value).toEqual([])
    expect(wizard.body.value.media).toEqual({ file: WIN11.file })
  })
})

describe('the request body', () => {
  it('has the profile, name, media with the edition index, every option and the resources', async () => {
    const wizard = await atSettings()
    wizard.variantIndex.value = 5
    wizard.setOption('defender', false)
    expect(wizard.body.value).toEqual({
      profile: 'windows',
      name: 'lab5',
      media: { file: WIN11.file, variant: '5' },
      options: { defender: false, decoys: false, sysmon: true, key: '', keyboard: 'Polish (Programmers)' },
      identity: {},
      resources: { vcpus: 2, ram_mb: 4096, disk_gb: 80 },
    })
  })

  it('leaves blank identity values out instead of sending empty strings', async () => {
    const wizard = await atSettings()
    wizard.account.value = 'Marta'
    wizard.machine.value = '   '
    wizard.password.value = ''
    expect(wizard.body.value.identity).toEqual({ account: 'Marta' })
  })

  it('sends the identity values the analyst typed, trimmed', async () => {
    const wizard = await atSettings()
    wizard.account.value = ' Marta '
    wizard.machine.value = 'DESKTOP-4K7QX2A'
    wizard.password.value = 'q7Zp-Lm2x-Rv9d'
    expect(wizard.body.value.identity).toEqual({ account: 'Marta', machine: 'DESKTOP-4K7QX2A', password: 'q7Zp-Lm2x-Rv9d' })
  })
})

describe('step 3, the review', () => {
  it('shows blank identity values as chosen at build time and a typed one as it is', async () => {
    const wizard = await atSettings()
    wizard.account.value = 'Marta'
    wizard.password.value = 'q7Zp-Lm2x-Rv9d'
    const rows = Object.fromEntries(wizard.reviewRows.value.map((row) => [row.label, row]))
    expect(rows['Username']).toMatchObject({ value: 'Marta', blank: false })
    expect(rows['Computer name']).toMatchObject({ value: 'chosen at build time', blank: true })
    expect(rows['Password']).toMatchObject({ value: 'set by you', blank: false })
  })

  it('lists the media, the guest name, the edition, the resources and every option with its value', async () => {
    const wizard = await atSettings()
    wizard.variantIndex.value = 5
    wizard.setOption('defender', false)
    const rows = Object.fromEntries(wizard.reviewRows.value.map((row) => [row.label, row.value]))
    expect(rows).toMatchObject({
      Media: WIN11.file,
      Name: 'lab5',
      Edition: 'Windows 11 Pro · pl-PL',
      Resources: '2 vCPUs · 4 GB RAM · 80 GB disk',
      'Microsoft Defender': 'OFF',
      'Make it look used': 'OFF',
      Sysmon: 'ON',
      'Product key': 'not set',
      'Keyboard layout': 'Polish (Programmers)',
    })
  })
})

describe('submitting', () => {
  async function atReview() {
    const wizard = await atSettings()
    wizard.next()
    return wizard
  }

  it('sends the body, is busy meanwhile and goes to the build page', async () => {
    const wizard = await atReview()
    const done = wizard.submit()
    expect(wizard.submission.submitting.value).toBe(true)
    await done
    expect(api.guestsStartBuild).toHaveBeenCalledWith(expect.objectContaining({ body: wizard.body.value }))
    expect(push).toHaveBeenCalledWith('/guest/builds/b-lab5')
  })

  it('does not send while the settings are invalid', async () => {
    const wizard = await atReview()
    wizard.name.value = 'Bad'
    await wizard.submit()
    expect(api.guestsStartBuild).not.toHaveBeenCalled()
  })

  it('puts a refused name on the name field and jumps back to the settings step', async () => {
    api.guestsStartBuild.mockResolvedValue(refused([{ field: 'name', message: 'is already used by another guest' }]))
    const wizard = await atReview()
    await wizard.submit()
    expect(wizard.errors.value.name).toBe('is already used by another guest')
    expect(wizard.step.value).toBe(2)
    expect(push).not.toHaveBeenCalled()
  })

  it('jumps to the earliest step that holds a refused field', async () => {
    api.guestsStartBuild.mockResolvedValue(
      refused([
        { field: 'identity.machine', message: "contains 'test', which tells a sample what the machine is" },
        { field: 'media.file', message: 'is not in the installation media list' },
      ]),
    )
    const wizard = await atReview()
    await wizard.submit()
    expect(wizard.step.value).toBe(1)
    expect(wizard.errors.value['media.file']).toBe('is not in the installation media list')
    expect(wizard.errors.value['identity.machine']).toMatch(/contains 'test'/)
  })

  it('maps an option, an edition and a resource to the settings step', async () => {
    expect(stepOfField('options.defender')).toBe(2)
    expect(stepOfField('media.variant')).toBe(2)
    expect(stepOfField('resources.disk_gb')).toBe(2)
    expect(stepOfField('identity.password')).toBe(2)
    expect(stepOfField('name')).toBe(2)
    expect(stepOfField('media.file')).toBe(1)
  })

  it('stays on the review with a banner for a conflict', async () => {
    api.guestsStartBuild.mockResolvedValue(failed('Another guest is being built: lab4', 409))
    const wizard = await atReview()
    await wizard.submit()
    expect(wizard.step.value).toBe(3)
    expect(wizard.submission.banner.value).toBe('Another guest is being built: lab4')
  })

  it('stays on the review when the only refusal is about a field the form has no input for', async () => {
    api.guestsStartBuild.mockResolvedValue(refused([{ field: 'profile', message: 'is not an installed profile (windows)' }]))
    const wizard = await atReview()
    await wizard.submit()
    expect(wizard.step.value).toBe(3)
    expect(wizard.submission.banner.value).toBe('profile is not an installed profile (windows)')
  })

  it('removes the server message from a field once the analyst edits it', async () => {
    api.guestsStartBuild.mockResolvedValue(refused([{ field: 'identity.machine', message: 'contains a giveaway' }]))
    const wizard = await atReview()
    await wizard.submit()
    expect(wizard.errors.value['identity.machine']).toBe('contains a giveaway')
    wizard.machine.value = 'LAPTOP-0000001'
    expect(wizard.errors.value['identity.machine']).toBeUndefined()
  })

  it('removes the server message from an option once it changes', async () => {
    api.guestsStartBuild.mockResolvedValue(refused([{ field: 'options.keyboard', message: 'must be one of US, German' }]))
    const wizard = await atReview()
    await wizard.submit()
    expect(wizard.errors.value['options.keyboard']).toBe('must be one of US, German')
    wizard.setOption('keyboard', 'US')
    expect(wizard.errors.value['options.keyboard']).toBeUndefined()
  })
})
