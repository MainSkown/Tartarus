import { describe, expect, it } from 'vitest'
import { MAX_TAG_NAME_LENGTH, checkTagName } from '@/services/tag-name'

describe('checkTagName', () => {
  it('lower-cases and trims what the analyst typed', () => {
    expect(checkTagName('  Phishing ')).toEqual({ name: 'phishing' })
  })

  it.each(['emotet', 'needs-review', 'a.b_c-1', 'tlp:amber', 'x'])('accepts %s', (raw) => {
    expect(checkTagName(raw)).toEqual({ name: raw })
  })

  it('accepts the longest name', () => {
    const longest = 'a'.repeat(MAX_TAG_NAME_LENGTH)
    expect(checkTagName(longest)).toEqual({ name: longest })
  })

  it('refuses an empty name without a message to show', () => {
    expect(checkTagName('   ')).toEqual({ problem: null })
  })

  it('refuses a name that is too long', () => {
    expect(checkTagName('a'.repeat(MAX_TAG_NAME_LENGTH + 1))).toEqual({
      problem: `at most ${MAX_TAG_NAME_LENGTH} characters`,
    })
  })

  it.each(['has space', 'under score!', 'ünicode', 'slash/name'])('refuses %s for its characters', (raw) => {
    expect(checkTagName(raw)).toEqual({ problem: "only a-z, 0-9, '.', '_' and '-'" })
  })

  it.each(['a:b:c', ':amber', 'tlp:', '::'])('refuses %s for its colons', (raw) => {
    expect(checkTagName(raw)).toEqual({ problem: "one ':' at most, between two parts" })
  })
})
