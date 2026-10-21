export default {
  title: 'SUBMIT SAMPLE',
  tabs: {
    sample: 'Sample',
    import: 'Import',
  },
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
    busy: 'busy',
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
  memory: {
    label: 'FULL MEMORY DUMP + VOLATILITY',
    warning: 'Adds about {gb} GB of disk and a few seconds of processing.',
    warningUnsized: 'Adds the guest RAM in disk space and a few seconds of processing.',
    keep: {
      label: 'KEEP THE DUMP AFTER THE FINDINGS ARE EXTRACTED',
      helper: 'Kept dumps stay on disk until the analysis is deleted.',
    },
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
  import: {
    title: 'IMPORT CAPTURE OR MEMORY IMAGE',
    file: {
      dropHint: 'drop a PCAP, PCAPNG or memory image here · or click to browse',
      label: 'Capture or memory image file',
      dropOneAtATime: 'Drop one file at a time',
    },
    kind: {
      capture: 'PCAP capture',
      memoryImage: 'Memory image',
      unsupported: 'Not a PCAP capture or a memory image',
    },
    limits: 'Limits: PCAP capture up to {capture}, memory image up to {memoryImage}.',
    memoryNote:
      'Windows 10 and 11 images only. When the build is unknown, symbols are fetched from Microsoft, which needs the cape container to reach the internet.',
    tooLarge: 'This file is larger than the {limit} limit for its kind.',
    uploading: 'Uploading {percent}%',
    blocked: {
      choose: 'Choose a capture or memory image to import',
    },
    error: {
      tooLarge: 'The backend refused the file: it is over the size limit.',
      unsupported: 'The backend does not accept this file type.',
    },
    actions: {
      import: '▶ IMPORT',
    },
  },
}
