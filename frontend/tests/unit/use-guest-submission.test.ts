import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StartResult } from '@/composables/use-guest-submission'
import { failed, succeeded } from './annotation-fixtures'

const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const { useGuestSubmission } = await import('@/composables/use-guest-submission')

const STARTED = { job_id: 7, build_id: 'b-lab5', guest: 'lab5' }
const PLACED = new Set(['name', 'identity.machine', 'resources.vcpus'])
const isPlaced = (field: string) => PLACED.has(field)

function refused(fields: { field: string; message: string }[]) {
  return failed(
    'Request validation failed',
    422,
    { fields: fields.map(({ field, message }) => ({ location: ['body', field], message, type: 'rejected' })) },
  )
}

beforeEach(() => {
  push.mockReset()
})

describe('useGuestSubmission', () => {
  it('goes to the build page of the guest that was started', async () => {
    const submission = useGuestSubmission(isPlaced)
    const unplaced = await submission.submit(async () => succeeded(STARTED))
    expect(unplaced).toEqual([])
    expect(push).toHaveBeenCalledWith('/guest/builds/b-lab5')
    expect(submission.banner.value).toBeUndefined()
  })

  it('is busy while the request is in flight and ignores a second press', async () => {
    const submission = useGuestSubmission(isPlaced)
    let finish: (value: StartResult) => void = () => undefined
    const send = vi.fn(() => new Promise<StartResult>((resolve) => (finish = resolve)))
    const first = submission.submit(send)
    expect(submission.submitting.value).toBe(true)
    await submission.submit(send)
    expect(send).toHaveBeenCalledTimes(1)
    finish(succeeded(STARTED))
    await first
    expect(submission.submitting.value).toBe(false)
  })

  it('puts each 422 message on the field it names and reports those fields in the order the server gave', async () => {
    const submission = useGuestSubmission(isPlaced)
    const placed = await submission.submit(async () =>
      refused([
        { field: 'identity.machine', message: "contains 'test', which tells a sample what the machine is" },
        { field: 'name', message: 'is already used by another guest' },
      ]),
    )
    expect(placed).toEqual(['identity.machine', 'name'])
    expect(submission.fieldErrors.value).toEqual({
      'identity.machine': "contains 'test', which tells a sample what the machine is",
      name: 'is already used by another guest',
    })
    expect(submission.banner.value).toBeUndefined()
    expect(push).not.toHaveBeenCalled()
  })

  it('keeps the first message when the server names a field twice', async () => {
    const submission = useGuestSubmission(isPlaced)
    await submission.submit(async () =>
      refused([
        { field: 'name', message: 'first' },
        { field: 'name', message: 'second' },
      ]),
    )
    expect(submission.fieldErrors.value).toEqual({ name: 'first' })
  })

  it('shows a message for a field the form has no input for in the banner', async () => {
    const submission = useGuestSubmission(isPlaced)
    const placed = await submission.submit(async () =>
      refused([
        { field: 'profile', message: 'is not an installed profile (windows)' },
        { field: 'resources.vcpus', message: 'must be between 1 and 8' },
      ]),
    )
    expect(placed).toEqual(['resources.vcpus'])
    expect(submission.banner.value).toBe('profile is not an installed profile (windows)')
    expect(submission.fieldErrors.value).toEqual({ 'resources.vcpus': 'must be between 1 and 8' })
  })

  it('shows the message of a 409 in the banner with no field marked', async () => {
    const submission = useGuestSubmission(isPlaced)
    const placed = await submission.submit(async () => failed('Another guest is being built: lab4', 409))
    expect(placed).toEqual([])
    expect(submission.banner.value).toBe('Another guest is being built: lab4')
    expect(submission.fieldErrors.value).toEqual({})
  })

  it('shows the envelope message of a 422 that names no field', async () => {
    const submission = useGuestSubmission(isPlaced)
    await submission.submit(async () => failed('The request body must be a JSON object', 422))
    expect(submission.banner.value).toBe('The request body must be a JSON object')
  })

  it('says something went wrong for an answer that is not an error envelope', async () => {
    const submission = useGuestSubmission(isPlaced)
    await submission.submit(async () => ({ data: undefined, error: undefined }))
    expect(submission.banner.value).toBe('Something went wrong talking to the backend.')
  })

  it('forgets the earlier refusal when the next attempt starts', async () => {
    const submission = useGuestSubmission(isPlaced)
    await submission.submit(async () => refused([{ field: 'name', message: 'taken' }]))
    await submission.submit(async () => failed('Another guest is being built: lab4', 409))
    expect(submission.fieldErrors.value).toEqual({})
    await submission.submit(async () => succeeded(STARTED))
    expect(submission.banner.value).toBeUndefined()
  })

  it('clears one field message when the analyst edits that field', async () => {
    const submission = useGuestSubmission(isPlaced)
    await submission.submit(async () =>
      refused([
        { field: 'name', message: 'taken' },
        { field: 'identity.machine', message: 'giveaway' },
      ]),
    )
    submission.clearFieldError('name')
    expect(submission.fieldErrors.value).toEqual({ 'identity.machine': 'giveaway' })
  })
})
