import { describe, expect, it } from 'vitest'
import { applySuggestion, tokenAt, type QueryToken } from '@/services/query-token'

/** The caret is written as `|` in the text, so each case reads as what the user sees. */
function at(marked: string): QueryToken {
  const caret = marked.indexOf('|')
  return tokenAt(marked.replace('|', ''), caret)
}

describe('tokenAt: field names', () => {
  it('finds a field prefix at the end of the text', () => {
    expect(at('pro|')).toEqual({ kind: 'field', prefix: 'pro', start: 0, end: 3 })
  })

  it('finds it in the middle of the word, replacing the whole word but prefixing up to the caret', () => {
    expect(at('pro|cess.name')).toEqual({ kind: 'field', prefix: 'pro', start: 0, end: 12 })
  })

  it('finds it with the caret at the start of the word', () => {
    expect(at('|pro')).toEqual({ kind: 'field', prefix: '', start: 0, end: 3 })
  })

  it('finds a word the caret touches at its start', () => {
    expect(at('a |b')).toEqual({ kind: 'field', prefix: '', start: 2, end: 3 })
  })

  it('finds the word after another term', () => {
    expect(at('lane:file pro|')).toEqual({ kind: 'field', prefix: 'pro', start: 10, end: 13 })
  })

  it('finds it after NOT and after an opening parenthesis', () => {
    expect(at('NOT pro|')).toMatchObject({ kind: 'field', prefix: 'pro', start: 4 })
    expect(at('(pro|')).toMatchObject({ kind: 'field', prefix: 'pro', start: 1 })
    expect(at('a AND (b OR pro|')).toMatchObject({ kind: 'field', prefix: 'pro', start: 12 })
  })

  it('stops the field name at the colon when the caret is inside it', () => {
    expect(at('pro|c:cmd.exe')).toEqual({ kind: 'field', prefix: 'pro', start: 0, end: 4 })
    expect(at('process.name|:cmd.exe')).toMatchObject({ kind: 'field', prefix: 'process.name', start: 0, end: 12 })
  })

  it('stops the field name at a comparison operator', () => {
    expect(at('destination.po|rt>=1024')).toEqual({ kind: 'field', prefix: 'destination.po', start: 0, end: 16 })
    expect(at('destination.port|>=1024')).toMatchObject({ kind: 'field', end: 16 })
  })

  it('takes field names with an @ and with dots', () => {
    expect(at('@time|')).toEqual({ kind: 'field', prefix: '@time', start: 0, end: 5 })
  })

  it('is none for a keyword, whatever its case', () => {
    expect(at('a AND|').kind).toBe('none')
    expect(at('a or|').kind).toBe('none')
    expect(at('NOT|').kind).toBe('none')
  })
})

describe('tokenAt: values', () => {
  it('finds the value right after the colon, with an empty prefix', () => {
    expect(at('process.name:|')).toEqual({ kind: 'value', field: 'process.name', prefix: '', start: 13, end: 13 })
  })

  it('finds the value typed so far', () => {
    expect(at('process.name:cm|')).toEqual({ kind: 'value', field: 'process.name', prefix: 'cm', start: 13, end: 15 })
  })

  it('replaces the whole value but prefixes up to the caret when the caret is inside it', () => {
    expect(at('process.name:c|md.exe')).toEqual({
      kind: 'value',
      field: 'process.name',
      prefix: 'c',
      start: 13,
      end: 20,
    })
  })

  it('lets a value hold colons', () => {
    expect(at('url:http://x|')).toEqual({ kind: 'value', field: 'url', prefix: 'http://x', start: 4, end: 12 })
  })

  it('finds the value after other terms', () => {
    expect(at('lane:file AND api:Nt|')).toMatchObject({ kind: 'value', field: 'api', prefix: 'Nt', start: 18 })
  })

  it('finds a quoted value, taking the opening quote into the replaced span but not into the prefix', () => {
    expect(at('process.name:"cmd e|')).toEqual({ kind: 'value', field: 'process.name', prefix: 'cmd e', start: 13, end: 19 })
  })

  it('takes the closing quote of a closed quoted value into the replaced span', () => {
    expect(at('process.name:"cmd e|xe" AND x')).toEqual({
      kind: 'value',
      field: 'process.name',
      prefix: 'cmd e',
      start: 13,
      end: 22,
    })
  })

  it('finds the value in a group, after the opening parenthesis', () => {
    expect(at('api:(|')).toEqual({ kind: 'value', field: 'api', prefix: '', start: 5, end: 5 })
    expect(at('api:(NtWr|')).toEqual({ kind: 'value', field: 'api', prefix: 'NtWr', start: 5, end: 9 })
  })

  it('finds the value in an unterminated group after OR', () => {
    expect(at('field:(a OR b|')).toEqual({ kind: 'value', field: 'field', prefix: 'b', start: 12, end: 13 })
    expect(at('api:(NtA OR NtB OR NtC|')).toMatchObject({ kind: 'value', field: 'api', prefix: 'NtC' })
  })

  it('offers values in a group after OR and a space', () => {
    expect(at('api:(a OR |')).toEqual({ kind: 'value', field: 'api', prefix: '', start: 10, end: 10 })
    expect(at('api:(a or |').kind).toBe('value')
  })

  it('offers nothing in a group after a value and a space', () => {
    expect(at('api:(a |').kind).toBe('none')
  })

  it('is none at the OR keyword inside a group', () => {
    expect(at('api:(a OR|').kind).toBe('none')
  })

  it('leaves a group once it is closed', () => {
    expect(at('api:(a OR b) pro|')).toMatchObject({ kind: 'field', prefix: 'pro' })
  })

  it('keeps the group field through a nested parenthesis', () => {
    expect(at('api:((a) OR b|')).toMatchObject({ kind: 'value', field: 'api', prefix: 'b' })
  })

  it('is none after a comparison operator: no values to offer for a range', () => {
    expect(at('destination.port>=10|').kind).toBe('none')
    expect(at('destination.port >= 10|').kind).toBe('none')
    expect(at('destination.port > |').kind).toBe('none')
  })
})

describe('tokenAt: nothing to complete', () => {
  it('is none on empty text', () => {
    expect(tokenAt('', 0)).toEqual({ kind: 'none', prefix: '', start: 0, end: 0 })
  })

  it('is none in whitespace between terms', () => {
    expect(at('lane:file |  AND x').kind).toBe('none')
  })

  it('is none inside a quoted free-text string', () => {
    expect(at('"powershell -e|nc"').kind).toBe('none')
    expect(at('lane:file "pow|').kind).toBe('none')
  })

  it('is none right after a closed quote and right before an opening one', () => {
    expect(at('"abc"|').kind).toBe('none')
    expect(at('|"abc"').kind).toBe('none')
  })

  it('is none beside a parenthesis only', () => {
    expect(at('()|').kind).toBe('none')
    expect(at('(|)').kind).toBe('none')
  })

  it('clamps a caret outside the text', () => {
    expect(tokenAt('pro', 99)).toMatchObject({ kind: 'field', prefix: 'pro' })
    expect(tokenAt('pro', -4)).toMatchObject({ kind: 'field', prefix: '' })
  })
})

describe('applySuggestion: fields', () => {
  it('replaces the typed prefix with the name and a colon, the caret after it', () => {
    const text = 'lane:file pro'
    const token = tokenAt(text, text.length)
    expect(applySuggestion(text, token, { kind: 'field', name: 'process.name' })).toEqual({
      text: 'lane:file process.name:',
      caret: 23,
    })
  })

  it('replaces the whole word when the caret was inside it', () => {
    const text = 'pro|cess.pid AND x'.replace('|', '')
    const token = tokenAt(text, 3)
    expect(applySuggestion(text, token, { kind: 'field', name: 'process.name' })).toEqual({
      text: 'process.name: AND x',
      caret: 13,
    })
  })

  it('does not add a second colon when one follows, and puts the caret after it', () => {
    const text = 'proc:cmd.exe'
    const token = tokenAt(text, 4)
    expect(applySuggestion(text, token, { kind: 'field', name: 'process.name' })).toEqual({
      text: 'process.name:cmd.exe',
      caret: 13,
    })
  })

  it('does not add a colon before a comparison operator', () => {
    const text = 'destination.po>=10'
    const token = tokenAt(text, 14)
    expect(applySuggestion(text, token, { kind: 'field', name: 'destination.port' })).toEqual({
      text: 'destination.port>=10',
      caret: 16,
    })
  })
})

describe('applySuggestion: values', () => {
  it('inserts a plain value at the token', () => {
    const text = 'process.name:cm'
    expect(applySuggestion(text, tokenAt(text, 15), { kind: 'value', value: 'cmd.exe' })).toEqual({
      text: 'process.name:cmd.exe',
      caret: 20,
    })
  })

  it('inserts into an empty value', () => {
    const text = 'process.name:'
    expect(applySuggestion(text, tokenAt(text, 13), { kind: 'value', value: 'cmd.exe' }).text).toBe('process.name:cmd.exe')
  })

  it('quotes a value that has a space', () => {
    const text = 'process.name:pro'
    expect(applySuggestion(text, tokenAt(text, 16), { kind: 'value', value: 'program files' }).text).toBe(
      'process.name:"program files"',
    )
  })

  it('quotes a value with parentheses or a quote, escaping the quote', () => {
    const text = 'summary:'
    expect(applySuggestion(text, tokenAt(text, 8), { kind: 'value', value: 'a(b)' }).text).toBe('summary:"a(b)"')
    expect(applySuggestion(text, tokenAt(text, 8), { kind: 'value', value: 'say "hi"' }).text).toBe('summary:"say \\"hi\\""')
  })

  it('doubles a trailing backslash inside quotes, because a quoted string cannot end in a single one', () => {
    const text = 'file.path:'
    expect(applySuggestion(text, tokenAt(text, 10), { kind: 'value', value: 'c:\\program files\\' }).text).toBe(
      'file.path:"c:\\program files\\\\"',
    )
  })

  it('leaves a path with backslashes but no spaces unquoted', () => {
    const text = 'file.path:'
    expect(applySuggestion(text, tokenAt(text, 10), { kind: 'value', value: 'c:\\windows\\cmd.exe' }).text).toBe(
      'file.path:c:\\windows\\cmd.exe',
    )
  })

  it('replaces a quoted value including its quotes', () => {
    const text = 'process.name:"cmd e" AND x'
    expect(applySuggestion(text, tokenAt(text, 18), { kind: 'value', value: 'cmd.exe' })).toEqual({
      text: 'process.name:cmd.exe AND x',
      caret: 20,
    })
  })

  it('inserts into a group', () => {
    const text = 'api:(NtA OR Nt'
    expect(applySuggestion(text, tokenAt(text, 14), { kind: 'value', value: 'NtWriteFile' }).text).toBe(
      'api:(NtA OR NtWriteFile',
    )
  })

  it('does nothing for a none token', () => {
    const token = tokenAt('', 0)
    expect(applySuggestion('', token, { kind: 'value', value: 'x' })).toEqual({ text: '', caret: 0 })
  })
})
