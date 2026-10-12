import { Notify } from 'quasar'
import { describe, expect, it, vi } from 'vitest'
import registerNotifyTypes from '@/boot/notify'

function registeredTypes() {
  const registerType = vi.spyOn(Notify, 'registerType')
  registerNotifyTypes({} as Parameters<typeof registerNotifyTypes>[0])
  return Object.fromEntries(registerType.mock.calls) as Record<string, Record<string, unknown>>
}

describe('notify boot', () => {
  it('registers exactly the four tt-* toast types', () => {
    expect(Object.keys(registeredTypes()).sort()).toEqual([
      'tt-error',
      'tt-info',
      'tt-success',
      'tt-warning',
    ])
  })

  it.each([
    ['tt-info', 'info', 'tt-toast tt-toast--info'],
    ['tt-success', 'check_circle', 'tt-toast tt-toast--success'],
    ['tt-warning', 'report', 'tt-toast tt-toast--warning'],
    ['tt-error', 'dangerous', 'tt-toast tt-toast--error'],
  ])('%s uses icon %s and classes "%s"', (type, icon, classes) => {
    expect(registeredTypes()[type]).toMatchObject({ icon, classes, position: 'bottom-right' })
  })

  it('auto-dismisses info, success and warning toasts after 5 seconds', () => {
    const types = registeredTypes()
    for (const type of ['tt-info', 'tt-success', 'tt-warning']) {
      expect(types[type]?.timeout).toBe(5000)
    }
  })

  it('keeps error toasts until dismissed', () => {
    expect(registeredTypes()['tt-error']?.timeout).toBe(0)
  })

  it('gives every toast a close action', () => {
    for (const options of Object.values(registeredTypes())) {
      expect(options.actions).toEqual([
        expect.objectContaining({ icon: 'close', round: true, flat: true }),
      ])
    }
  })
})
