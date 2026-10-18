export default {
  viewLabel: 'Detections view',
  modes: {
    detections: 'DETECTIONS',
    attack: 'ATT&CK',
  },
  empty: {
    detections: 'no detections',
    attack: 'no ATT&CK techniques were raised',
  },
  list: {
    events: '{count} event | {count} events',
  },
  technique: {
    filter: 'technique {id}',
    filterNamed: 'technique {id} ({name})',
    clear: '[CLEAR]',
  },
  matrix: {
    version: 'ATT&CK v{version}',
    cell: '{id}, {hits} hit, {severity} severity | {id}, {hits} hits, {severity} severity',
    cellNamed: '{id}, {name}, {hits} hit, {severity} severity | {id}, {name}, {hits} hits, {severity} severity',
  },
  detail: {
    heading: 'DESCRIPTION',
    filterOnRule: '[FILTER ON RULE]',
    noDescription: 'no description',
    ruleset: 'RULESET',
    process: 'PROCESS',
    time: 'TIME',
    techniques: 'TECHNIQUES',
    references: 'REFERENCES',
    matchedCondition: 'MATCHED CONDITION',
    triggeringEvents: 'TRIGGERING EVENTS',
    triggeringEventsNoun: 'the triggering events',
    eventsShown: '{shown} of {total} shown',
    queryNames: 'the query names {used} of {listed}',
    showTheseEvents: '[SHOW THESE EVENTS]',
    noTriggeringEvents: '> no triggering events recorded',
  },
}
