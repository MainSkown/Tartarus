import { mount } from '@vue/test-utils'
import { Quasar, QInput } from 'quasar'
import { describe, expect, it } from 'vitest'
import type { ArchiveMemberRead } from '@/api'
import SubmitArchiveFields from '@/components/SubmitArchiveFields.vue'

function member(name: string, overrides: Partial<ArchiveMemberRead> = {}): ArchiveMemberRead {
  return { name, size: 2048, encrypted: true, unsafe: false, unsupported: false, ...overrides }
}

type Props = InstanceType<typeof SubmitArchiveFields>['$props']

function mountFields(props: Partial<Props> = {}) {
  return mount(SubmitArchiveFields, {
    props: { members: [], loading: false, passwordOk: undefined, password: 'infected', entry: '', ...props },
    global: { plugins: [Quasar] },
  })
}

function lastEntry(wrapper: ReturnType<typeof mountFields>): string | undefined {
  return wrapper.emitted<[string]>('update:entry')?.at(-1)?.[0]
}

function radioFor(wrapper: ReturnType<typeof mountFields>, name: string) {
  return wrapper.find<HTMLInputElement>(`input[type="radio"][value="${name}"]`)
}

function passwordInput(wrapper: ReturnType<typeof mountFields>) {
  return wrapper.findComponent(QInput)
}

describe('SubmitArchiveFields', () => {
  describe('the file to run', () => {
    it('lists each member with its name and size', () => {
      const wrapper = mountFields({ members: [member('payload.exe', { size: 2048 }), member('readme.txt', { size: 12 })] })

      const rows = wrapper.findAll('.member-row')
      expect(rows.map((row) => row.find('.member-name').text())).toEqual(['payload.exe', 'readme.txt'])
      expect(rows.map((row) => row.find('.member-size').text())).toEqual(['2 KB', '12 B'])
    })

    it('titles the list FILE TO RUN', () => {
      expect(mountFields({ members: [member('a.exe')] }).find('.archive-entry-title').text()).toBe('FILE TO RUN')
    })

    it('is a radio group that the keyboard can walk: one native radio per member', () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')] })

      expect(wrapper.find('[role="radiogroup"]').attributes('aria-label')).toBe('Files in the archive')
      const radios = wrapper.findAll<HTMLInputElement>('input[type="radio"]')
      expect(radios).toHaveLength(2)
      expect(new Set(radios.map((radio) => radio.element.name)).size).toBe(1)
    })

    it('preselects the only member', () => {
      const wrapper = mountFields({ members: [member('only.exe')] })
      expect(lastEntry(wrapper)).toBe('only.exe')
    })

    it('preselects nothing when there are several members', () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe'), member('c.dll')] })
      expect(wrapper.emitted('update:entry')).toBeUndefined()
    })

    it('preselects the only member that can be chosen when the others are shown but refused', () => {
      const wrapper = mountFields({ members: [member('../evil.exe', { unsafe: true }), member('good.exe')] })
      expect(lastEntry(wrapper)).toBe('good.exe')
    })

    it('emits the member the analyst picks', async () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')] })

      await radioFor(wrapper, 'b.exe').setValue(true)

      expect(lastEntry(wrapper)).toBe('b.exe')
    })

    it('shows the chosen member as checked and selected', () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')], entry: 'b.exe' })

      expect(radioFor(wrapper, 'b.exe').element.checked).toBe(true)
      expect(radioFor(wrapper, 'a.exe').element.checked).toBe(false)
      expect(wrapper.findAll('.member-row--selected')).toHaveLength(1)
    })

    it('keeps the choice when the list is read again and the member is still there', async () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')], entry: 'b.exe' })

      await wrapper.setProps({ members: [member('a.exe'), member('b.exe')] })

      expect(wrapper.emitted('update:entry')).toBeUndefined()
    })

    it('forgets the choice when the member is no longer listed', async () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')], entry: 'b.exe' })

      await wrapper.setProps({ members: [member('a.exe'), member('c.exe')] })

      expect(lastEntry(wrapper)).toBe('')
    })

    it('forgets the choice when the list is emptied for another file', async () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')], entry: 'b.exe' })

      await wrapper.setProps({ members: [] })

      expect(lastEntry(wrapper)).toBe('')
    })

    it('forgets a choice that is not in the list it was mounted with', () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')], entry: 'gone.exe' })
      expect(lastEntry(wrapper)).toBe('')
    })

    it('refuses to choose a member that is unsafe or unsupported, and says why', () => {
      const wrapper = mountFields({
        members: [
          member('ok.exe'),
          member('../evil.exe', { unsafe: true }),
          member('a,b.exe', { unsupported: true }),
        ],
      })

      expect(radioFor(wrapper, 'ok.exe').element.disabled).toBe(false)
      expect(radioFor(wrapper, '../evil.exe').element.disabled).toBe(true)
      expect(radioFor(wrapper, 'a,b.exe').element.disabled).toBe(true)
      const chips = wrapper.findAll('.member-reason').map((chip) => chip.text())
      expect(chips).toEqual(['UNSAFE', 'NOT SUPPORTED'])
    })

    it('never emits a refused member, even when the entry prop names it', () => {
      const wrapper = mountFields({
        members: [member('ok.exe'), member('../evil.exe', { unsafe: true }), member('b.exe')],
        entry: '../evil.exe',
      })
      expect(lastEntry(wrapper)).toBe('')
    })

    it('gives a long name a title with the whole name and leaves it to truncate', () => {
      const longName = `dir/${'very-long-name-'.repeat(12)}.exe`
      const wrapper = mountFields({ members: [member(longName), member('b.exe')] })

      const name = wrapper.find('.member-name')
      expect(name.text()).toBe(longName)
      expect(name.attributes('title')).toBe(longName)
    })

    it('shows a loading line, and no list, while the first list is read', () => {
      const wrapper = mountFields({ loading: true })

      expect(wrapper.find('.archive-loading').text()).toBe('Reading the archive…')
      expect(wrapper.find('[role="radiogroup"]').exists()).toBe(false)
    })

    it('keeps the list on screen, marked busy, while it is read again', () => {
      const wrapper = mountFields({ loading: true, members: [member('a.exe'), member('b.exe')] })

      expect(wrapper.find('.archive-loading').exists()).toBe(false)
      expect(wrapper.find('[role="radiogroup"]').attributes('aria-busy')).toBe('true')
    })

    it('says so when the archive holds no files', () => {
      const wrapper = mountFields()
      expect(wrapper.find('.archive-empty').text()).toBe('This archive holds no files.')
    })

    it('says nothing about being empty while it loads', () => {
      expect(mountFields({ loading: true }).find('.archive-empty').exists()).toBe(false)
    })

    it('shows the backend refusal of the chosen member under the list', () => {
      const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')], entryError: 'not a member of the archive' })
      expect(wrapper.find('.archive-entry-error').text()).toBe('not a member of the archive')
    })
  })

  describe('the password', () => {
    it('shows the value it is given', () => {
      const wrapper = mountFields({ members: [member('a.exe')], password: 'infected' })
      expect(passwordInput(wrapper).props('modelValue')).toBe('infected')
    })

    it('emits what the analyst types', async () => {
      const wrapper = mountFields({ members: [member('a.exe')] })

      await passwordInput(wrapper).find('input').setValue('hunter2')

      expect(wrapper.emitted<[string]>('update:password')?.at(-1)?.[0]).toBe('hunter2')
    })

    it('is required while any member is encrypted', () => {
      const wrapper = mountFields({ members: [member('a.exe', { encrypted: true })] })
      expect(passwordInput(wrapper).props('label')).toBe('ARCHIVE PASSWORD')
    })

    it('is marked optional when no member is encrypted', () => {
      const wrapper = mountFields({ members: [member('a.txt', { encrypted: false })] })
      expect(passwordInput(wrapper).props('label')).toBe('ARCHIVE PASSWORD (OPTIONAL)')
    })

    it('is not called optional before the list says so', () => {
      expect(passwordInput(mountFields({ loading: true })).props('label')).toBe('ARCHIVE PASSWORD')
    })

    it('says the password does not open the archive when the verdict is false', () => {
      const wrapper = mountFields({ members: [member('a.exe')], passwordOk: false })

      expect(passwordInput(wrapper).props('error')).toBe(true)
      expect(passwordInput(wrapper).props('errorMessage')).toBe('The password does not open the archive')
    })

    it.each([true, null, undefined])('shows no error when the verdict is %s', (verdict) => {
      const wrapper = mountFields({ members: [member('a.exe')], passwordOk: verdict })
      expect(passwordInput(wrapper).props('error')).toBe(false)
    })

    it('does not show the verdict on an earlier password while the answer to the new one is awaited', () => {
      const wrapper = mountFields({ members: [member('a.exe')], passwordOk: false, loading: true })
      expect(passwordInput(wrapper).props('error')).toBe(false)
    })

    it('shows the backend refusal of the password in place of the verdict', () => {
      const wrapper = mountFields({
        members: [member('a.exe')],
        passwordOk: false,
        passwordError: 'must not have leading or trailing whitespace',
      })
      expect(passwordInput(wrapper).props('errorMessage')).toBe('must not have leading or trailing whitespace')
    })
  })

  it('disables the password and the list while the analysis is being submitted', () => {
    const wrapper = mountFields({ members: [member('a.exe'), member('b.exe')], disable: true })

    expect(passwordInput(wrapper).props('disable')).toBe(true)
    expect(radioFor(wrapper, 'a.exe').element.disabled).toBe(true)
  })
})
