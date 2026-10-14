import { describe, expect, it } from 'vitest'
import { FACET_FIELDS, fieldLabel } from '@/services/event-fields'

describe('fieldLabel', () => {
  it('gives the facet fields a short name', () => {
    expect(fieldLabel('process.name')).toBe('PROCESS')
    expect(fieldLabel('tartarus.lane')).toBe('LANE')
    expect(fieldLabel('event.action')).toBe('ACTION')
    expect(fieldLabel('api.name')).toBe('API')
    expect(fieldLabel('destination.domain')).toBe('DOMAIN')
    expect(fieldLabel('rule.name')).toBe('RULE')
  })

  it('labels every facet field', () => {
    for (const field of FACET_FIELDS) expect(fieldLabel(field)).not.toBe(field.toUpperCase())
  })

  it('falls back to the field name in capitals for any other field', () => {
    expect(fieldLabel('file.path')).toBe('FILE.PATH')
  })
})
