import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import { defineComponent } from 'vue'
import { i18n, n, t, type MessageKey } from '@/i18n'

const asKey = (key: string) => key as MessageKey

describe('the shared instance', () => {
  it('translates a catalogue key', () => {
    expect(t('guests.card.default')).toBe('DEFAULT')
  })

  it('rejects an unknown key at compile time', () => {
    // @ts-expect-error a key that is not in the en-US catalogue is a type error
    expect(t('guests.card.noSuchKey')).toBe('guests.card.noSuchKey')
  })

  it('interpolates named values', () => {
    expect(t('guests.build.failure.step', { step: 'TAMPER OFF' })).toBe('TAMPER OFF FAILED')
  })

  it('formats a number with the named en-US format', () => {
    expect(n(12431, 'count')).toBe('12,431')
  })
})

describe('plural messages', () => {
  i18n.global.mergeLocaleMessage('en-US', { probe: { events: '{count} event | {count} events' } })

  it.each([
    [0, '0 events'],
    [1, '1 event'],
    [2, '2 events'],
  ])('picks the form for %i like `count === 1 ? singular : plural`', (count, expected) => {
    expect(t(asKey('probe.events'), count)).toBe(expected)
  })

  it('shows a count formatted by the caller when the named value is given', () => {
    expect(t(asKey('probe.events'), { count: n(12431, 'count') }, 12431)).toBe('12,431 events')
  })
})

const Probe = defineComponent({
  template: `<p>{{ $t("guests.card.default") }}<i18n-t keypath="guests.card.default" scope="global" tag="b" />
    <i18n-t keypath="probe.intro" scope="global" tag="span"><template #guide><a href="/guide">the guide</a></template></i18n-t></p>`,
})

describe('message syntax', () => {
  i18n.global.mergeLocaleMessage('en-US', { probe: { mail: "write to a{'@'}b.c {'|'} or {'{'}here{'}'}", intro: 'Read {guide} first' } })

  it('prints the characters that are syntax when they are written as literal interpolations', () => {
    expect(t(asKey('probe.mail'))).toBe('write to a@b.c | or {here}')
  })

  it('puts markup into a message through component interpolation, not HTML', () => {
    const wrapper = mount(Probe)
    expect(wrapper.get('span').text()).toBe('Read the guide first')
    expect(wrapper.get('a').attributes('href')).toBe('/guide')
  })
})

describe('the plugin installed by the vitest setup file', () => {
  it('makes `$t` and `<i18n-t>` work in a mount that passes no plugins', () => {
    expect(mount(Probe).text()).toContain('DEFAULTDEFAULT')
  })

  it('keeps working when a mount passes its own plugins', () => {
    expect(mount(Probe, { global: { plugins: [Quasar] } }).text()).toContain('DEFAULTDEFAULT')
  })
})
