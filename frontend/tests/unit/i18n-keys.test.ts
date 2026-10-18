import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import enUS from '@/i18n/en-US'

const FRONTEND = join(import.meta.dirname, '../..')
const SRC = join(FRONTEND, 'src')
const NOT_SCANNED = [join(SRC, 'api'), join(SRC, 'i18n')]

const LITERAL_CALL = /(?<![\w$.])t\(\s*(['"])([^'"`]+)\1/g
const TEMPLATE_CALL = /(?<![\w$.])t\(\s*`([^`]*)`/g
const QUOTED_STRING = /(['"])([\w.]+)\1/g
const KEYPATH_ATTRIBUTE = /<(?:I18nT|i18n-t)\b[^>]*?\bkeypath=(['"])([^'"]+)\1/gi

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (NOT_SCANNED.includes(path)) return []
    if (entry.isDirectory()) return sourceFiles(path)
    return /\.(vue|ts)$/.test(entry.name) ? [path] : []
  })
}

function catalogueLeaves(tree: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([name, value]) => {
    const path = `${prefix}${name}`
    return typeof value === 'string' ? [path] : catalogueLeaves(value as Record<string, unknown>, `${path}.`)
  })
}

const escapeRegExp = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// A template key such as `guests.build.step.${status}` matches each leaf its literal parts allow.
const templatePattern = (template: string) =>
  new RegExp(`^${template.split(/\$\{[^}]*\}/).map(escapeRegExp).join('.+')}$`)

interface KeyUsages {
  literal: Map<string, string[]>
  quoted: Set<string>
  templates: { source: string; file: string; pattern: RegExp }[]
}

const captures = (source: string, pattern: RegExp, group: number): string[] =>
  [...source.matchAll(pattern)].map((match) => match[group] ?? '')

function collectUsages(files: string[]): KeyUsages {
  const usages: KeyUsages = { literal: new Map(), quoted: new Set(), templates: [] }
  const addLiteral = (key: string, file: string) => usages.literal.set(key, [...(usages.literal.get(key) ?? []), file])

  for (const file of files) {
    const source = readFileSync(file, 'utf8')
    const relativePath = relative(FRONTEND, file)
    captures(source, QUOTED_STRING, 2).forEach((key) => usages.quoted.add(key))
    captures(source, LITERAL_CALL, 2).forEach((key) => addLiteral(key, relativePath))
    captures(source, KEYPATH_ATTRIBUTE, 2).forEach((key) => addLiteral(key, relativePath))
    for (const template of captures(source, TEMPLATE_CALL, 1)) {
      if (template.includes('${')) usages.templates.push({ source: template, file: relativePath, pattern: templatePattern(template) })
      else addLiteral(template, relativePath)
    }
  }
  return usages
}

const usages = collectUsages(sourceFiles(SRC))
const leaves = catalogueLeaves(enUS)
const isUsed = (leaf: string) =>
  usages.quoted.has(leaf) || usages.templates.some(({ pattern }) => pattern.test(leaf))

describe('i18n key usage in src', () => {
  it('uses only keys that exist in the en-US catalogue', () => {
    const unknownLiterals = [...usages.literal]
      .filter(([key]) => !leaves.includes(key))
      .map(([key, files]) => `"${key}" used in ${files.join(', ')} is not in the en-US catalogue`)
    const emptyTemplates = usages.templates
      .filter(({ pattern }) => !leaves.some((leaf) => pattern.test(leaf)))
      .map(({ source, file }) => `\`${source}\` used in ${file} matches no key in the en-US catalogue`)

    expect([...unknownLiterals, ...emptyTemplates]).toEqual([])
  })

  it('uses every key of the en-US catalogue', () => {
    const unusedLeaves = leaves
      .filter((leaf) => !isUsed(leaf))
      .map((leaf) => `"${leaf}" is defined in src/i18n/en-US/${leaf.split('.')[0]}.ts but no t() or keypath in src uses it`)

    expect(unusedLeaves).toEqual([])
  })
})
