import { mount } from '@vue/test-utils'
import { Quasar, QInput } from 'quasar'
import { describe, expect, it } from 'vitest'
import GuestResourcesFields from '@/components/guest/GuestResourcesFields.vue'

type Props = InstanceType<typeof GuestResourcesFields>['$props']

function mountFields(props: Partial<Props> = {}) {
  return mount(GuestResourcesFields, {
    global: { plugins: [Quasar] },
    props: { modelValue: { vcpus: 2, ram_mb: 4096, disk_gb: 80 }, ...props },
  })
}

describe('GuestResourcesFields', () => {
  it('has a numeric input with its unit for vCPUs, RAM and disk', () => {
    const inputs = mountFields().findAllComponents(QInput)
    expect(inputs.map((input) => [input.props('label'), input.props('modelValue'), input.props('suffix')])).toEqual([
      ['VCPUS', 2, undefined],
      ['RAM', 4096, 'MB'],
      ['DISK', 80, 'GB'],
    ])
  })

  it('emits the whole value with one number changed', async () => {
    const wrapper = mountFields()
    await wrapper.findAll('input')[1]!.setValue('8192')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([{ vcpus: 2, ram_mb: 8192, disk_gb: 80 }])
  })

  it('emits zero for a cleared field, which the form then refuses', async () => {
    const wrapper = mountFields()
    await wrapper.findAll('input')[0]!.setValue('')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([{ vcpus: 0, ram_mb: 4096, disk_gb: 80 }])
  })

  it('says the profile minimum next to the disk', () => {
    expect(mountFields({ minDisk: 64 }).text()).toContain('minimum 64 GB')
  })

  it('shows an error on the field it names', () => {
    const wrapper = mountFields({ errors: { 'resources.disk_gb': 'At least 64 GB' } })
    const [vcpus, , disk] = wrapper.findAllComponents(QInput)
    expect(vcpus!.props('error')).toBe(false)
    expect(disk!.props('error')).toBe(true)
    expect(disk!.props('errorMessage')).toBe('At least 64 GB')
  })

  it('locks the disk and gives the reason', () => {
    const wrapper = mountFields({ diskLocked: true, diskReason: 'a clone has its source disk' })
    const [, , disk] = wrapper.findAllComponents(QInput)
    expect(disk!.props('disable')).toBe(true)
    expect(wrapper.text()).toContain('a clone has its source disk')
  })

  it('disables every field while busy', () => {
    const inputs = mountFields({ disable: true }).findAllComponents(QInput)
    expect(inputs.every((input) => input.props('disable') === true)).toBe(true)
  })
})
