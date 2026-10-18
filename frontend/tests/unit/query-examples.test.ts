import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import { QUERY_EXAMPLES } from '@/services/query-examples'

const SPEC = readFileSync(path.resolve(process.cwd(), '..', 'docs', 'specs', 'backend.md'), 'utf8')

describe('QUERY_EXAMPLES', () => {
  it('has eight examples, each with a description', () => {
    expect(QUERY_EXAMPLES).toHaveLength(8)
    expect(QUERY_EXAMPLES.every((example) => example.description.length > 0)).toBe(true)
  })

  it('describes each example with a catalogue message', () => {
    for (const { description } of QUERY_EXAMPLES) expect(i18n.global.te(description), description).toBe(true)
  })

  it('takes every query from the backend spec, so the cheat sheet cannot drift from it', () => {
    for (const { query } of QUERY_EXAMPLES) expect(SPEC, query).toContain(query)
  })

  it('has no example twice', () => {
    expect(new Set(QUERY_EXAMPLES.map((example) => example.query)).size).toBe(QUERY_EXAMPLES.length)
  })
})
