import { effectScope, nextTick, ref, shallowRef, type EffectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ArchiveMemberRead, ArchiveMembersRead } from '@/api'
import { failed, succeeded } from './annotation-fixtures'

const analysesArchiveMembers = vi.fn()
vi.mock('@/api', () => ({ analysesArchiveMembers: (...args: unknown[]) => analysesArchiveMembers(...args) }))

const { useArchiveMembers } = await import('@/composables/use-archive-members')

const PASSWORD_DEBOUNCE_MS = 400

function member(name: string, overrides: Partial<ArchiveMemberRead> = {}): ArchiveMemberRead {
  return { name, size: 1024, encrypted: true, unsafe: false, unsupported: false, ...overrides }
}

function listing(members: ArchiveMemberRead[], passwordOk: boolean | null = true): ArchiveMembersRead {
  return { members, password_ok: passwordOk }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const ONE = listing([member('payload.exe')])
const ZIP = new File(['x'], 'sample.zip')
const OTHER_ZIP = new File(['y'], 'other.zip')
const PLAIN = new File(['MZ'], 'invoice.exe')

let scope: EffectScope

function start(initialFile?: File, initialPassword = 'infected') {
  const file = shallowRef<File | undefined>(initialFile)
  const password = ref(initialPassword)
  const archive = scope.run(() => useArchiveMembers(file, password))!
  return { file, password, archive }
}

const settle = () => vi.advanceTimersByTimeAsync(0)

beforeEach(() => {
  vi.useFakeTimers()
  analysesArchiveMembers.mockReset()
  scope = effectScope()
})

afterEach(() => {
  scope.stop()
  vi.useRealTimers()
})

describe('useArchiveMembers', () => {
  describe('a file that is not a zip', () => {
    it('asks nothing and holds nothing', async () => {
      const { archive } = start(PLAIN)
      await settle()

      expect(analysesArchiveMembers).not.toHaveBeenCalled()
      expect(archive.isArchive.value).toBe(false)
      expect(archive.members.value).toEqual([])
      expect(archive.loading.value).toBe(false)
    })

    it('clears a zip that was listed before', async () => {
      analysesArchiveMembers.mockResolvedValue(succeeded(ONE))
      const { file, archive } = start(ZIP)
      await settle()
      expect(archive.members.value).toHaveLength(1)

      file.value = PLAIN
      await settle()

      expect(archive.isArchive.value).toBe(false)
      expect(archive.members.value).toEqual([])
      expect(archive.passwordOk.value).toBeUndefined()
      expect(archive.error.value).toBeUndefined()
    })

    it('clears the error of a zip that failed before', async () => {
      analysesArchiveMembers.mockResolvedValue(failed('Not a zip file', 422))
      const { file, archive } = start(ZIP)
      await settle()
      expect(archive.error.value).toBe('Not a zip file')

      file.value = PLAIN
      await settle()

      expect(archive.error.value).toBeUndefined()
    })

    it('clears everything when the file is removed', async () => {
      analysesArchiveMembers.mockResolvedValue(succeeded(ONE))
      const { file, archive } = start(ZIP)
      await settle()

      file.value = undefined
      await settle()

      expect(archive.isArchive.value).toBe(false)
      expect(archive.members.value).toEqual([])
    })
  })

  describe('a zip', () => {
    it('is loading until the list arrives, then holds the members and the password verdict', async () => {
      const reply = deferred<ReturnType<typeof succeeded>>()
      analysesArchiveMembers.mockReturnValue(reply.promise)
      const { archive } = start(ZIP)
      await settle()

      expect(archive.isArchive.value).toBe(true)
      expect(archive.loading.value).toBe(true)
      expect(archive.members.value).toEqual([])

      reply.resolve(succeeded(listing([member('a.exe'), member('b.dll')], true)))
      await settle()

      expect(archive.loading.value).toBe(false)
      expect(archive.members.value.map((listed) => listed.name)).toEqual(['a.exe', 'b.dll'])
      expect(archive.passwordOk.value).toBe(true)
      expect(archive.error.value).toBeUndefined()
    })

    it('sends the file and the password, and leaves the refusal to the dialog', async () => {
      analysesArchiveMembers.mockResolvedValue(succeeded(ONE))
      start(ZIP, 'hunter2')
      await settle()

      expect(analysesArchiveMembers).toHaveBeenCalledTimes(1)
      const [options] = analysesArchiveMembers.mock.calls[0]!
      expect(options.body).toEqual({ file: ZIP, password: 'hunter2' })
      expect(options.meta).toEqual({ quietStatuses: [413, 422] })
    })

    it('recognises a zip by its first bytes when the name does not say so', async () => {
      analysesArchiveMembers.mockResolvedValue(succeeded(ONE))
      const sample = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], 'sample.bin')
      const { archive } = start(sample)

      await vi.waitFor(() => expect(archive.isArchive.value).toBe(true))
      await vi.waitFor(() => expect(archive.members.value).toHaveLength(1))
    })

    it('keeps a null password verdict as null: nothing was encrypted', async () => {
      analysesArchiveMembers.mockResolvedValue(succeeded(listing([member('a.txt', { encrypted: false })], null)))
      const { archive } = start(ZIP)
      await settle()

      expect(archive.passwordOk.value).toBeNull()
    })

    it('reports a wrong password as a verdict, not as an error', async () => {
      analysesArchiveMembers.mockResolvedValue(succeeded(listing([member('a.exe')], false)))
      const { archive } = start(ZIP)
      await settle()

      expect(archive.passwordOk.value).toBe(false)
      expect(archive.error.value).toBeUndefined()
      expect(archive.members.value).toHaveLength(1)
    })

    it('turns a 422 into the API message and empties the list', async () => {
      analysesArchiveMembers.mockResolvedValue(failed('The file is not a zip archive', 422))
      const { archive } = start(ZIP)
      await settle()

      expect(archive.error.value).toBe('The file is not a zip archive')
      expect(archive.members.value).toEqual([])
      expect(archive.loading.value).toBe(false)
      expect(archive.isArchive.value).toBe(true)
    })

    it('says something generic when the failure has no envelope', async () => {
      analysesArchiveMembers.mockResolvedValue({ data: undefined, error: undefined })
      const { archive } = start(ZIP)
      await settle()

      expect(archive.error.value).toBeTruthy()
    })

    it('forgets the earlier error when a later query succeeds', async () => {
      analysesArchiveMembers.mockResolvedValueOnce(failed('Corrupt central directory', 422))
      analysesArchiveMembers.mockResolvedValueOnce(succeeded(ONE))
      const { file, archive } = start(ZIP)
      await settle()

      file.value = OTHER_ZIP
      await settle()

      expect(archive.error.value).toBeUndefined()
      expect(archive.members.value).toHaveLength(1)
    })
  })

  describe('a stale response', () => {
    it('does not overwrite the list of a zip chosen since', async () => {
      const slow = deferred<ReturnType<typeof succeeded>>()
      analysesArchiveMembers.mockReturnValueOnce(slow.promise)
      analysesArchiveMembers.mockResolvedValueOnce(succeeded(listing([member('new.exe')])))
      const { file, archive } = start(ZIP)
      await settle()

      file.value = OTHER_ZIP
      await settle()
      slow.resolve(succeeded(listing([member('old.exe')])))
      await settle()

      expect(archive.members.value.map((listed) => listed.name)).toEqual(['new.exe'])
    })

    it('does not bring back the list of a zip once a non-zip is chosen', async () => {
      const slow = deferred<ReturnType<typeof succeeded>>()
      analysesArchiveMembers.mockReturnValueOnce(slow.promise)
      const { file, archive } = start(ZIP)
      await settle()

      file.value = PLAIN
      await settle()
      slow.resolve(succeeded(ONE))
      await settle()

      expect(archive.members.value).toEqual([])
      expect(archive.loading.value).toBe(false)
    })

    it('does not let a slow failure replace the list of a newer password', async () => {
      const slow = deferred<ReturnType<typeof failed>>()
      analysesArchiveMembers.mockReturnValueOnce(slow.promise)
      analysesArchiveMembers.mockResolvedValueOnce(succeeded(ONE))
      const { password, archive } = start(ZIP)
      await settle()

      password.value = 'other'
      await vi.advanceTimersByTimeAsync(PASSWORD_DEBOUNCE_MS)
      slow.resolve(failed('too late', 422))
      await settle()

      expect(archive.error.value).toBeUndefined()
      expect(archive.members.value).toHaveLength(1)
    })
  })

  describe('a changed password', () => {
    beforeEach(() => analysesArchiveMembers.mockResolvedValue(succeeded(ONE)))

    it('asks again with the new password after a pause in typing, and not before', async () => {
      const { password } = start(ZIP)
      await settle()
      analysesArchiveMembers.mockClear()

      password.value = 'hunter2'
      await vi.advanceTimersByTimeAsync(PASSWORD_DEBOUNCE_MS - 1)
      expect(analysesArchiveMembers).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(1)
      expect(analysesArchiveMembers).toHaveBeenCalledTimes(1)
      expect(analysesArchiveMembers.mock.calls[0]![0].body.password).toBe('hunter2')
    })

    it('asks once for a burst of keystrokes', async () => {
      const { password } = start(ZIP)
      await settle()
      analysesArchiveMembers.mockClear()

      for (const typed of ['h', 'hu', 'hun']) {
        password.value = typed
        await vi.advanceTimersByTimeAsync(100)
      }
      await vi.advanceTimersByTimeAsync(PASSWORD_DEBOUNCE_MS)

      expect(analysesArchiveMembers).toHaveBeenCalledTimes(1)
      expect(analysesArchiveMembers.mock.calls[0]![0].body.password).toBe('hun')
    })

    it('is loading from the first keystroke, so a verdict on the old password is not trusted', async () => {
      const { password, archive } = start(ZIP)
      await settle()
      expect(archive.loading.value).toBe(false)

      password.value = 'h'
      await nextTick()

      expect(archive.loading.value).toBe(true)
      await vi.advanceTimersByTimeAsync(PASSWORD_DEBOUNCE_MS)
      expect(archive.loading.value).toBe(false)
    })

    it('keeps the listed members while the new answer is on its way', async () => {
      const { password, archive } = start(ZIP)
      await settle()

      password.value = 'h'
      await nextTick()

      expect(archive.members.value).toHaveLength(1)
    })

    it('asks nothing when the file is not a zip', async () => {
      const { password } = start(PLAIN)
      await settle()

      password.value = 'hunter2'
      await vi.advanceTimersByTimeAsync(PASSWORD_DEBOUNCE_MS * 2)

      expect(analysesArchiveMembers).not.toHaveBeenCalled()
    })

    it('drops the pending question when a non-zip replaces the zip', async () => {
      const { file, password } = start(ZIP)
      await settle()
      analysesArchiveMembers.mockClear()

      password.value = 'h'
      await nextTick()
      file.value = PLAIN
      await vi.advanceTimersByTimeAsync(PASSWORD_DEBOUNCE_MS * 2)

      expect(analysesArchiveMembers).not.toHaveBeenCalled()
    })

    it('drops the pending question when the scope ends', async () => {
      const { password } = start(ZIP)
      await settle()
      analysesArchiveMembers.mockClear()

      password.value = 'h'
      await nextTick()
      scope.stop()
      await vi.advanceTimersByTimeAsync(PASSWORD_DEBOUNCE_MS * 2)

      expect(analysesArchiveMembers).not.toHaveBeenCalled()
    })
  })
})
