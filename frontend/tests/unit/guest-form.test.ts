import { describe, expect, it } from 'vitest'
import {
  BLANK_IDENTITY_LABEL,
  guestNameProblem,
  identityProblem,
  optionValueLabel,
  profileDefaults,
  resourceProblems,
  withoutBlanks,
} from '@/services/guest-form'
import { DEFENDER_OPTION, KEY_OPTION, KEYBOARD_OPTION, windowsProfile } from './guest-wizard-fixtures'

describe('guestNameProblem', () => {
  it.each(['lab1', 'win11-clean', 'a1', 'x'.repeat(32)])('accepts %s', (name) => {
    expect(guestNameProblem(name, [])).toBeUndefined()
  })

  it.each([
    ['empty', ''],
    ['one letter', 'a'],
    ['33 characters', 'x'.repeat(33)],
    ['a capital', 'Lab1'],
    ['starting with a digit', '1lab'],
    ['starting with a hyphen', '-lab'],
    ['an underscore', 'lab_1'],
    ['a space', 'lab 1'],
  ])('refuses %s with the rule', (_label, name) => {
    expect(guestNameProblem(name, [])).toMatch(/2 to 32 lower-case letters, digits or hyphens/)
  })

  it('refuses a name another guest already has', () => {
    expect(guestNameProblem('lab1', ['lab1', 'lab2'])).toBe('Another guest is already called lab1')
  })
})

describe('identityProblem', () => {
  const { account, machine, password } = windowsProfile().identity

  it('has nothing to say about a blank value: it is chosen at build time', () => {
    expect(identityProblem(account, '')).toBeUndefined()
  })

  it('accepts a value that matches the whole pattern', () => {
    expect(identityProblem(account, 'Marta')).toBeUndefined()
    expect(identityProblem(machine, 'DESKTOP-4K7QX2A')).toBeUndefined()
  })

  it('refuses a value that matches only part of the pattern', () => {
    expect(identityProblem(account, 'Marta Kowalska')).toBe('Username must match [A-Za-z][A-Za-z0-9_-]{0,19}')
  })

  it('refuses a computer name made only of digits (a lookahead in the profile pattern)', () => {
    expect(identityProblem(machine, '12345')).toMatch(/^Computer name must match/)
  })

  it('refuses a reserved name whatever its case', () => {
    expect(identityProblem(account, 'administrator')).toBe('administrator is reserved')
  })

  it('applies the password pattern to length', () => {
    expect(identityProblem(password, 'short')).toMatch(/^Password must match/)
    expect(identityProblem(password, 'long enough 1')).toBeUndefined()
  })

  it('does not block on a pattern the browser cannot read', () => {
    expect(identityProblem({ ...account, pattern: '(?P<x>a)' }, 'anything')).toBeUndefined()
  })
})

describe('resourceProblems', () => {
  const GOOD = { vcpus: 2, ram_mb: 4096, disk_gb: 80 }

  it('is empty for sensible values', () => {
    expect(resourceProblems(GOOD, 64)).toEqual({})
  })

  it('refuses a disk under the profile minimum and says the minimum', () => {
    expect(resourceProblems({ ...GOOD, disk_gb: 40 }, 64)).toEqual({ disk_gb: 'At least 64 GB' })
  })

  it('refuses zero, negative and fractional counts', () => {
    expect(resourceProblems({ vcpus: 0, ram_mb: -1, disk_gb: 80.5 }, 64)).toEqual({
      vcpus: 'A whole number of at least 1',
      ram_mb: 'A whole number of at least 1',
      disk_gb: 'A whole number of at least 1',
    })
  })
})

describe('profileDefaults', () => {
  it('takes every option default and the profile resources, without the minimum disk', () => {
    const { options, resources } = profileDefaults(windowsProfile())
    expect(options).toEqual({ defender: true, decoys: false, sysmon: true, key: '', keyboard: 'Polish (Programmers)' })
    expect(resources).toEqual({ vcpus: 2, ram_mb: 4096, disk_gb: 80 })
  })

  it('falls back to a type-appropriate value for an option with no default', () => {
    const profile = windowsProfile({
      options: [
        { key: 'a', label: 'A', type: 'bool' },
        { key: 'b', label: 'B', type: 'string' },
        { key: 'c', label: 'C', type: 'choice', choices: ['x', 'y'] },
      ],
    })
    expect(profileDefaults(profile).options).toEqual({ a: false, b: '', c: 'x' })
  })
})

describe('optionValueLabel', () => {
  it('writes a bool as ON or OFF', () => {
    expect(optionValueLabel(DEFENDER_OPTION, true)).toBe('ON')
    expect(optionValueLabel(DEFENDER_OPTION, false)).toBe('OFF')
  })

  it('never writes a secret out, only whether one is set', () => {
    expect(optionValueLabel(KEY_OPTION, 'AAAAA-BBBBB-CCCCC-DDDDD-EEEEE')).toBe('set')
    expect(optionValueLabel(KEY_OPTION, '')).toBe('not set')
  })

  it('writes a choice or a string as it is, and an empty string as none', () => {
    expect(optionValueLabel(KEYBOARD_OPTION, 'US')).toBe('US')
    expect(optionValueLabel({ ...KEYBOARD_OPTION, type: 'string' }, '')).toBe('none')
  })
})

describe('withoutBlanks', () => {
  it('drops the empty values and keeps the rest as they are', () => {
    expect(withoutBlanks({ account: 'Marta', machine: '', password: ' two words ' })).toEqual({ account: 'Marta', password: ' two words ' })
  })
})

describe('BLANK_IDENTITY_LABEL', () => {
  it('says the value is chosen later', () => {
    expect(BLANK_IDENTITY_LABEL).toBe('chosen at build time')
  })
})
