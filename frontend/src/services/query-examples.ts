import type { MessageKey } from '@/i18n'

export interface QueryExample {
  query: string
  /** A catalogue key: the cheat sheet shows the translated sentence beside the query. */
  description: MessageKey
}

/** The spec's own examples (backend spec, "Query language"), for the cheat sheet to fill the bar with. */
export const QUERY_EXAMPLES: QueryExample[] = [
  { query: 'process.name:cmd.exe AND lane:network', description: 'events.cheatSheet.examples.network' },
  {
    query: 'api:(NtWriteVirtualMemory OR NtCreateThreadEx) NOT process.name:"explorer.exe"',
    description: 'events.cheatSheet.examples.injection',
  },
  { query: 'file.path:*\\\\AppData\\\\Roaming\\\\*.exe', description: 'events.cheatSheet.examples.appData' },
  {
    query: 'destination.port >= 1024 AND dns.question.name:*.onion',
    description: 'events.cheatSheet.examples.numberRange',
  },
  { query: 'rule.ruleset:sigma AND event.severity >= 3', description: 'events.cheatSheet.examples.sigma' },
  { query: 'powershell -enc', description: 'events.cheatSheet.examples.freeText' },
  { query: 'process.name:CMD.EXE', description: 'events.cheatSheet.examples.caseInsensitive' },
  { query: '@timestamp:2026-10-13', description: 'events.cheatSheet.examples.wholeDay' },
]
