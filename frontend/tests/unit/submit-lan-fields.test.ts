import { mount } from '@vue/test-utils'
import { Quasar, QToggle } from 'quasar'
import { describe, expect, it } from 'vitest'
import type { LanHost, LanPreset } from '@/api'
import SubmitLanFields from '@/components/SubmitLanFields.vue'

function host(role: string, n: number): LanHost {
  return { fqdn: `${role}${n}.corp.local`, address: `192.168.150.${200 + n}`, role, services: [{ kind: 'smb', port: 445 }] }
}

const OFFICE: LanPreset = {
  id: 'small-office',
  name: 'Small office',
  description: 'A domain controller, a file server and two workstations.',
  hosts: [host('domain-controller', 1), host('file-server', 2), host('workstation', 3), host('workstation', 4)],
}
const HOME: LanPreset = {
  id: 'flat-home',
  name: 'Flat home LAN',
  description: 'A NAS and a laptop.',
  hosts: [host('nas', 1), host('laptop', 2)],
}

type Props = InstanceType<typeof SubmitLanFields>['$props']

function mountFields(props: Partial<Props> = {}) {
  return mount(SubmitLanFields, {
    props: { enabled: true, preset: null, presets: [OFFICE, HOME], loading: false, ...props },
    global: { plugins: [Quasar] },
  })
}

type Wrapper = ReturnType<typeof mountFields>

const toggle = (wrapper: Wrapper) => wrapper.findComponent(QToggle)
const radio = (wrapper: Wrapper, id: string) => wrapper.find<HTMLInputElement>(`input[type="radio"][value="${id}"]`)

describe('SubmitLanFields', () => {
  describe('the switch', () => {
    it('is labelled SIMULATE LOCAL NETWORK and says what off means', () => {
      const wrapper = mountFields({ enabled: false })

      expect(toggle(wrapper).text()).toBe('SIMULATE LOCAL NETWORK')
      expect(wrapper.find('.lan-note').text()).toBe('The guest sees the gateway and nothing else on its network.')
    })

    it('shows no picker while off', () => {
      const wrapper = mountFields({ enabled: false })

      expect(wrapper.find('[role="radiogroup"]').exists()).toBe(false)
      expect(wrapper.find('.loader').exists()).toBe(false)
    })

    it('asks the owner to turn on and off', async () => {
      const wrapper = mountFields({ enabled: false })

      await toggle(wrapper).trigger('click')

      expect(wrapper.emitted<[boolean]>('update:enabled')?.at(-1)).toEqual([true])
    })

    it('says what on means once on', () => {
      expect(mountFields().find('.lan-note').text()).toContain('Fake hosts answer on the guest network')
    })

    it('is disabled with an explanation when the route is internet', () => {
      const wrapper = mountFields({ enabled: false, routeRefused: true })

      expect(toggle(wrapper).props('disable')).toBe(true)
      expect(wrapper.find('.lan-note').text()).toBe(
        'Not available with the internet route: pick another route to simulate a local network.',
      )
    })

    it('is disabled while the form is being submitted', () => {
      expect(toggle(mountFields({ disable: true })).props('disable')).toBe(true)
    })
  })

  describe('the preset picker', () => {
    it('is a radio group with one native radio per preset', () => {
      const wrapper = mountFields()

      expect(wrapper.find('[role="radiogroup"]').attributes('aria-label')).toBe('Local network presets')
      expect(wrapper.findAll<HTMLInputElement>('input[type="radio"]')).toHaveLength(2)
    })

    it('shows each preset by name with its description and a summary of its hosts', () => {
      const wrapper = mountFields()

      const [office, home] = wrapper.findAll('.preset-row')
      expect(office!.find('.preset-name').text()).toBe('Small office')
      expect(office!.find('.preset-description').text()).toBe('A domain controller, a file server and two workstations.')
      expect(office!.find('.preset-hosts').text()).toBe('4 hosts: domain-controller, file-server, workstation ×2')
      expect(home!.find('.preset-hosts').text()).toBe('2 hosts: nas, laptop')
    })

    it('checks the chosen preset and none other', () => {
      const wrapper = mountFields({ preset: 'flat-home' })

      expect(radio(wrapper, 'flat-home').element.checked).toBe(true)
      expect(radio(wrapper, 'small-office').element.checked).toBe(false)
      expect(wrapper.findAll('.preset-row--selected')).toHaveLength(1)
    })

    it('checks nothing while no preset is chosen', () => {
      const wrapper = mountFields({ preset: null })

      expect(wrapper.findAll('input[type="radio"]').every((input) => !(input.element as HTMLInputElement).checked)).toBe(true)
    })

    it('emits the id of the preset that is picked', async () => {
      const wrapper = mountFields()

      await radio(wrapper, 'small-office').setValue(true)

      expect(wrapper.emitted<[string]>('update:preset')?.at(-1)).toEqual(['small-office'])
    })

    it('disables the radios while the form is being submitted', () => {
      const wrapper = mountFields({ disable: true })

      expect(radio(wrapper, 'small-office').element.disabled).toBe(true)
    })

    it('shows the backend refusal of the preset under the list', () => {
      const wrapper = mountFields({ presetError: 'Unknown local network preset' })

      expect(wrapper.find('.preset-error').text()).toBe('Unknown local network preset')
      expect(wrapper.find('.preset-error').attributes('role')).toBe('alert')
    })
  })

  describe('while the presets are not there', () => {
    it('shows the loader instead of the list while loading', () => {
      const wrapper = mountFields({ presets: [], loading: true })

      expect(wrapper.find('.loader').exists()).toBe(true)
      expect(wrapper.find('[role="radiogroup"]').exists()).toBe(false)
    })

    it('shows the failure with a retry that asks the owner to load again', async () => {
      const wrapper = mountFields({ presets: [], error: 'The guest control service is not reachable' })

      expect(wrapper.text()).toContain('failed to load: The guest control service is not reachable')
      await wrapper.find('.retry-btn').trigger('click')

      expect(wrapper.emitted('retry')).toHaveLength(1)
    })

    it('says there are no presets when the list is empty', () => {
      expect(mountFields({ presets: [] }).text()).toContain('> no local network presets')
    })
  })
})
