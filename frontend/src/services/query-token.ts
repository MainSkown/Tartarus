export type QueryToken =
  | { kind: 'none'; prefix: string; start: number; end: number }
  | { kind: 'field'; prefix: string; start: number; end: number }
  | { kind: 'value'; field: string; prefix: string; start: number; end: number }

export type QuerySuggestion = { kind: 'field'; name: string } | { kind: 'value'; value: string }

interface Lexeme {
  kind: 'word' | 'quoted' | 'open' | 'close'
  start: number
  end: number
  closed?: boolean
}

const KEYWORDS = new Set(['AND', 'OR', 'NOT'])
const OPERATOR_START = /[:<>]/
const OPERATOR_ONLY = /^[<>=]+$/
const NEEDS_QUOTES = /[\s()"]/

function quotedEnd(text: string, open: number): { end: number; closed: boolean } {
  for (let index = open + 1; index < text.length; index++) {
    if (text[index] === '\\') index++
    else if (text[index] === '"') return { end: index + 1, closed: true }
  }
  return { end: text.length, closed: false }
}

function lex(text: string): Lexeme[] {
  const lexemes: Lexeme[] = []
  let index = 0
  while (index < text.length) {
    const character = text[index]!
    if (/\s/.test(character)) {
      index++
    } else if (character === '(' || character === ')') {
      lexemes.push({ kind: character === '(' ? 'open' : 'close', start: index, end: index + 1 })
      index++
    } else if (character === '"') {
      const { end, closed } = quotedEnd(text, index)
      lexemes.push({ kind: 'quoted', start: index, end, closed })
      index = end
    } else {
      const start = index
      while (index < text.length && !/[\s()"]/.test(text[index]!)) index++
      lexemes.push({ kind: 'word', start, end: index })
    }
  }
  return lexemes
}

function touches(lexeme: Lexeme, caret: number): boolean {
  if (lexeme.kind === 'word') return lexeme.start <= caret && caret <= lexeme.end
  if (lexeme.kind !== 'quoted') return false
  const insideEnd = lexeme.closed ? lexeme.end - 1 : lexeme.end
  return lexeme.start < caret && caret <= insideEnd
}

/** The field a `field:` word names when the next lexeme is glued to it, else undefined. */
function fieldNamedBy(text: string, lexeme: Lexeme | undefined, next: Lexeme): string | undefined {
  if (lexeme?.kind !== 'word' || lexeme.end !== next.start) return undefined
  const word = text.slice(lexeme.start, lexeme.end)
  return word.endsWith(':') ? word.slice(0, -1) : undefined
}

/** For each lexeme, the field of the `field:( ... )` group it sits in, if any. */
function groupFields(text: string, lexemes: Lexeme[]): (string | undefined)[] {
  const stack: (string | undefined)[] = []
  return lexemes.map((lexeme, position) => {
    if (lexeme.kind === 'open') {
      const named = fieldNamedBy(text, lexemes[position - 1], lexeme)
      stack.push(named ?? stack[stack.length - 1])
      return stack[stack.length - 1]
    }
    if (lexeme.kind === 'close') return stack.pop()
    return stack[stack.length - 1]
  })
}

function none(caret: number): QueryToken {
  return { kind: 'none', prefix: '', start: caret, end: caret }
}

function wordToken(text: string, word: Lexeme, caret: number, groupField: string | undefined): QueryToken {
  const content = text.slice(word.start, word.end)
  if (OPERATOR_ONLY.test(content) || KEYWORDS.has(content.toUpperCase())) return none(caret)

  if (groupField !== undefined) {
    return { kind: 'value', field: groupField, prefix: text.slice(word.start, caret), start: word.start, end: word.end }
  }

  const operatorAt = content.search(OPERATOR_START)
  if (operatorAt < 0) return { kind: 'field', prefix: text.slice(word.start, caret), start: word.start, end: word.end }

  const operatorIndex = word.start + operatorAt
  if (caret <= operatorIndex) {
    return { kind: 'field', prefix: text.slice(word.start, caret), start: word.start, end: operatorIndex }
  }
  if (content[operatorAt] !== ':') return none(caret)
  return {
    kind: 'value',
    field: content.slice(0, operatorAt),
    prefix: text.slice(operatorIndex + 1, caret),
    start: operatorIndex + 1,
    end: word.end,
  }
}

function quotedToken(text: string, quoted: Lexeme, caret: number, owner: string | undefined): QueryToken {
  if (owner === undefined) return none(caret)
  return { kind: 'value', field: owner, prefix: text.slice(quoted.start + 1, caret), start: quoted.start, end: quoted.end }
}

function comparisonOperand(text: string, previous: Lexeme | undefined): boolean {
  return previous?.kind === 'word' && OPERATOR_ONLY.test(text.slice(previous.start, previous.end))
}

/** A group's value that has not been started: right after `field:(` or after an `OR` and a space. */
function emptyValueInGroup(text: string, lexemes: Lexeme[], caret: number): QueryToken {
  const before = lexemes.filter((lexeme) => lexeme.end <= caret)
  const last = before[before.length - 1]
  const startsValue =
    last?.kind === 'open' ||
    (last?.kind === 'word' && last.end < caret && text.slice(last.start, last.end).toUpperCase() === 'OR')
  const field = startsValue ? groupFields(text, lexemes)[before.length - 1] : undefined
  if (field === undefined) return none(caret)
  return { kind: 'value', field, prefix: '', start: caret, end: caret }
}

/** What the caret is on: a field name or a value being typed (with the span to replace), or nothing to complete. */
export function tokenAt(text: string, caret: number): QueryToken {
  const position = Math.min(Math.max(caret, 0), text.length)
  const lexemes = lex(text)
  const index = lexemes.findIndex((lexeme) => touches(lexeme, position))
  if (index < 0) return emptyValueInGroup(text, lexemes, position)

  const lexeme = lexemes[index]!
  const previous = lexemes[index - 1]
  if (comparisonOperand(text, previous)) return none(position)
  const groupField = groupFields(text, lexemes)[index]

  if (lexeme.kind === 'quoted') {
    const owner = groupField ?? fieldNamedBy(text, previous, lexeme)
    return quotedToken(text, lexeme, position, owner)
  }
  return wordToken(text, lexeme, position, groupField)
}

function quoteValue(value: string): string {
  if (value !== '' && !NEEDS_QUOTES.test(value)) return value
  const escaped = value.replace(/"/g, '\\"').replace(/\\$/, '\\\\')
  return `"${escaped}"`
}

/** The text with the token replaced by the chosen suggestion, and where the caret goes. */
export function applySuggestion(
  text: string,
  token: QueryToken,
  suggestion: QuerySuggestion,
): { text: string; caret: number } {
  if (token.kind === 'none') return { text, caret: token.start }
  const before = text.slice(0, token.start)
  const after = text.slice(token.end)

  if (suggestion.kind === 'value') {
    const inserted = quoteValue(suggestion.value)
    return { text: `${before}${inserted}${after}`, caret: before.length + inserted.length }
  }

  const name = suggestion.name
  const followedByColon = after.startsWith(':')
  const followedByOperator = /^[<>]/.test(after)
  const separator = followedByColon || followedByOperator ? '' : ':'
  const caret = before.length + name.length + (followedByColon || separator ? 1 : 0)
  return { text: `${before}${name}${separator}${after}`, caret }
}
