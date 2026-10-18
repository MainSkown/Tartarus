export default {
  title: 'SUBMIT SAMPLE',
  file: {
    dropHint: 'drop file here · or click to browse',
    label: 'Sample file',
    dropOneAtATime: 'Drop one file at a time',
    hash: 'sha256 {hash}',
    hashing: 'hashing…',
  },
  guest: {
    label: 'GUEST',
    none: 'none ready',
    loading: 'loading…',
    unavailable: 'The guest list could not be loaded: the backend picks the default guest.',
    openGuestVm: '[OPEN GUEST VM]',
  },
  route: {
    title: 'NETWORK',
    group: 'Network route',
    internetWarning: "Sample will reach the real internet from this host's public IP.",
  },
  timeout: {
    label: 'TIMEOUT',
    unit: 's',
    range: 'Whole seconds, {min} to {max}',
    minutes: '{minutes} min',
  },
  package: {
    label: 'PACKAGE',
  },
  interactive: {
    label: 'INTERACTIVE DESKTOP',
    off: 'The run ends once the sample has exited, or at the timeout.',
    on: 'Drive the guest yourself. The run lasts the full timeout unless you press END RUN on the live page.',
    onWithLength:
      'Drive the guest yourself. The run lasts the full timeout ({minutes}) unless you press END RUN on the live page.',
  },
  blocked: {
    chooseSample: 'Choose a sample to analyse',
  },
  error: {
    unreachable: 'Could not reach the backend.',
  },
  actions: {
    detonate: '▶ DETONATE',
  },
}
