export default {
  header: {
    wordmark: 'TARTARUS',
    reconnecting: 'Reconnecting…',
    submit: '+ SUBMIT',
    queue: 'QUEUE {count}',
  },
  live: {
    single: 'LIVE #{id} {clock}',
    count: 'LIVE {count}',
    menuLabel: 'Running analyses',
    menuTitle: 'no analysis running | 1 analysis running | {count} analyses running',
    item: '#{id} {filename}',
    meta: '{guest} · {clock}',
    noGuest: 'no guest',
  },
  nav: {
    dashboard: 'Dashboard',
    rules: 'Rules',
    search: 'Search',
    guestVm: 'Guest VM',
    settings: 'Settings',
  },
  health: {
    cape: 'CAPE',
    guest: 'Guest',
    store: 'Store',
    postgres: 'Postgres',
    opensearch: 'OpenSearch',
    withMessage: '{status} — {message}',
    detail: '{label}: {description}',
  },
  apiError: {
    generic: 'Something went wrong talking to the backend.',
  },
  update: {
    ready: 'A new version of Tartarus is ready.',
    reload: 'RELOAD',
  },
}
