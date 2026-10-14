export interface QueryExample {
  query: string
  description: string
}

/** The spec's own examples (backend spec, "Query language"), for the cheat sheet to fill the bar with. */
export const QUERY_EXAMPLES: QueryExample[] = [
  { query: 'process.name:cmd.exe AND lane:network', description: 'network events of one process' },
  {
    query: 'api:(NtWriteVirtualMemory OR NtCreateThreadEx) NOT process.name:"explorer.exe"',
    description: 'injection calls from any process but explorer',
  },
  { query: 'file.path:*\\\\AppData\\\\Roaming\\\\*.exe', description: 'executables written under AppData\\Roaming' },
  {
    query: 'destination.port >= 1024 AND dns.question.name:*.onion',
    description: 'a number range together with a wildcard',
  },
  { query: 'rule.ruleset:sigma AND event.severity >= 3', description: 'Sigma detections of high severity or above' },
  { query: 'powershell -enc', description: 'free text: both words, anywhere they can be searched' },
  { query: 'process.name:CMD.EXE', description: 'values are case-insensitive' },
  { query: '@timestamp:2026-10-13', description: 'a date alone is the whole day' },
]
