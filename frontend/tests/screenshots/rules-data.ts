import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type { RuleRead } from '../../src/api/types.gen'

const RULES_ROOT = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..', '..', 'rules', 'sigma')
const CONTAINER_ROOT = '/rules/sigma'

function yamlFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(directory, entry.name)
    if (entry.isDirectory()) return yamlFiles(full)
    return entry.name.endsWith('.yml') ? [full] : []
  })
}

function scalar(text: string, key: string): string | null {
  return text.match(new RegExp(`^${key}:\\s*(.+)$`, 'm'))?.[1]?.trim() ?? null
}

function descriptionOf(text: string): string | null {
  const folded = text.match(/^description:\s*>-?\s*\n((?:[ \t]+.+\n?)+)/m)?.[1]
  return folded ? folded.split('\n').map((line) => line.trim()).filter(Boolean).join(' ') : scalar(text, 'description')
}

function tagsOf(text: string): string[] {
  const block = text.match(/^tags:\s*\n((?:\s+- .+\n)+)/m)?.[1] ?? ''
  return [...block.matchAll(/- (.+)/g)].map((match) => match[1]!.trim())
}

const yamlByPath = new Map<string, string>()

function fromShippedFile(file: string, hits: number, overrides: Partial<RuleRead> = {}): RuleRead {
  const text = readFileSync(file, 'utf8')
  const containerPath = `${CONTAINER_ROOT}/${path.relative(RULES_ROOT, file).split(path.sep).join('/')}`
  yamlByPath.set(containerPath, text)
  return {
    id: scalar(text, 'id')!,
    title: scalar(text, 'title')!,
    description: descriptionOf(text),
    level: scalar(text, 'level'),
    status: scalar(text, 'status'),
    tags: tagsOf(text),
    logsource_category: text.match(/^\s+category:\s*(\S+)/m)?.[1] ?? null,
    validity: 'valid',
    error: null,
    enabled: true,
    path: containerPath,
    hits,
    ...overrides,
  }
}

function custom(id: string, file: string, yaml: string, overrides: Partial<RuleRead>): RuleRead {
  const containerPath = `${CONTAINER_ROOT}/custom/${file}`
  yamlByPath.set(containerPath, yaml)
  return {
    id,
    title: scalar(yaml, 'title') ?? file,
    description: scalar(yaml, 'description'),
    level: scalar(yaml, 'level'),
    status: scalar(yaml, 'status'),
    tags: [],
    logsource_category: yaml.match(/^\s+category:\s*(\S+)/m)?.[1] ?? null,
    validity: 'valid',
    error: null,
    enabled: true,
    path: containerPath,
    hits: 0,
    ...overrides,
  }
}

// Hit counts picked to show a zero, small numbers, ties and one that needs thousands separators.
const SHIPPED_HITS: Record<string, number> = {
  'tartarus_selftest_registry_marker.yml': 7,
  'dns_query_win_mal_cobaltstrike.yml': 3,
  'create_remote_thread_win_powershell_susp_targets.yml': 12,
  'proc_creation_win_susp_double_extension.yml': 3,
  'registry_set_uac_disable.yml': 1,
  'proc_creation_win_hktl_sliver_c2_execution_pattern.yml': 1_204,
}

const SHIPPED_FILES = yamlFiles(RULES_ROOT)
  .sort()
  .filter((file, index) => file.includes('tartarus') || index % 3 === 0)
  .slice(0, 24)

const BROKEN_YAML = `title: Suspicious Child Of Office Application (draft)
id: 0b8a6f3e-5c1d-4d52-9a0e-6a1f2d9c7e11
status: experimental
description: Work in progress, copied from a blog post
logsource:
    category: process_creation
    product: windows
detection:
    selection:
        ParentImage|endswith: '\\winword.exe'
    condition: selection and not selection_img
level: high
`

const CORRELATION_YAML = `title: Many Failed Logons Followed By A Success
id: 5d3c9a10-77aa-4f0e-8b1d-2f6e4c3a9b01
status: test
description: Counts failed logons per user, which needs aggregation over time windows
logsource:
    category: process_creation
    product: windows
detection:
    failed:
        CommandLine|contains: 'logon failed'
    condition: failed | count() by User > 10
level: medium
`

const IMAGE_LOAD_YAML = `title: Unsigned DLL Loaded By A System Binary
id: 9e4b2c77-18d3-4a65-b0f2-7c1d8a5e3f90
status: test
description: Needs image_load events, which Tartarus does not derive from capemon
logsource:
    category: image_load
    product: windows
detection:
    selection:
        Signed: 'false'
    condition: selection
level: high
`

const LONG_TITLE = 'Suspicious PowerShell Download Cradle Using Invoke-WebRequest With Encoded Command And Hidden Window Followed By Scheduled Task Persistence'
const LONG_YAML = `title: ${LONG_TITLE}
id: c4f7e0aa-2b19-4a9f-8e36-1d5b7a9c2e44
status: test
description: Detects a long chain of behaviour in one rule, with a title that never ends
logsource:
    category: process_creation
    product: windows
detection:
    selection:
        CommandLine|contains|all:
            - 'powershell'
            - '-enc'
            - 'Invoke-WebRequest'
    condition: selection
level: high
`

const CUSTOM_RULES: RuleRead[] = [
  custom('0b8a6f3e-5c1d-4d52-9a0e-6a1f2d9c7e11', 'office_child_draft.yml', BROKEN_YAML, {
    validity: 'invalid',
    level: 'high',
    error: "Condition references 'selection_img', which is not defined in the detection",
    enabled: false,
  }),
  custom('5d3c9a10-77aa-4f0e-8b1d-2f6e4c3a9b01', 'failed_logons_correlation.yml', CORRELATION_YAML, {
    validity: 'unsupported',
    level: 'medium',
    error: 'aggregation conditions (count(), near) are not supported',
    enabled: false,
  }),
  custom('9e4b2c77-18d3-4a65-b0f2-7c1d8a5e3f90', 'unsigned_dll_system_binary.yml', IMAGE_LOAD_YAML, {
    validity: 'unsupported',
    level: 'high',
    error: "logsource category 'image_load' has no events in Tartarus",
    enabled: false,
    logsource_category: 'image_load',
  }),
  custom(
    'c4f7e0aa-2b19-4a9f-8e36-1d5b7a9c2e44',
    `team_rules/threat_hunting/powershell/${'very_long_directory_name_'.repeat(3)}download_cradle_encoded_hidden_persistence.yml`,
    LONG_YAML,
    { title: LONG_TITLE, level: 'high', hits: 48_213 },
  ),
]

/** The shipped rules from the repository, a few of the analyst's own, and one of every awkward kind. */
export const SCREENSHOT_RULES: RuleRead[] = [
  ...SHIPPED_FILES.map((file) => fromShippedFile(file, SHIPPED_HITS[path.basename(file)] ?? 0)),
  ...CUSTOM_RULES,
].map((rule, index) => (index === 5 || index === 11 ? { ...rule, enabled: false } : rule))

export function yamlOf(rule: RuleRead): string {
  return yamlByPath.get(rule.path) ?? `title: ${rule.title}\n`
}

export const VALID_SELECTED = SCREENSHOT_RULES.find((rule) => rule.title.startsWith('Suspicious Cobalt Strike DNS'))!
export const SELF_TEST = SCREENSHOT_RULES.find((rule) => rule.path.includes('/tartarus/'))!
export const INVALID_RULE = SCREENSHOT_RULES.find((rule) => rule.validity === 'invalid')!
export const UNSUPPORTED_RULE = SCREENSHOT_RULES.find((rule) => rule.validity === 'unsupported')!
export const LONG_RULE = SCREENSHOT_RULES.find((rule) => rule.title === LONG_TITLE)!
