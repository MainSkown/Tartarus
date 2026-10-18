export default {
  export: {
    button: '[EXPORT]',
    iocs: 'IOCS',
    report: 'REPORT',
    preparing: 'Preparing the {format} IOCs…',
    downloaded: '{format} IOCs downloaded',
  },
  dialog: {
    title: 'REPORT',
    id: '#{id}',
    format: 'FORMAT',
    formatGroup: 'Report format',
    include: 'INCLUDE',
    generate: '[GENERATE]',
    progress: 'Report progress',
    progressNote: 'You can close this: the report keeps building in the background and a toast tells you when it is ready.',
    percent: '{percent}%',
    ready: '> report ready',
    newReport: '[NEW REPORT]',
    download: '[DOWNLOAD {format}]',
  },
  option: {
    notes: {
      label: 'NOTES',
      hint: 'Your notes on the analysis, its processes and its events. Tags always stay.',
    },
    screenshots: {
      label: 'SCREENSHOTS',
      hint: 'The guest screenshots, embedded in the file. Off keeps it much smaller.',
    },
    rawIocs: {
      label: 'RAW IOCS',
      hint: 'Every IOC of each type. Off lists only the first five per type.',
    },
  },
  blocked: {
    notFinished: 'Reports are built from a finished analysis',
  },
  job: {
    interrupted: 'The backend restarted while the report was being built',
    failed: 'The report could not be built',
  },
  notice: {
    ready: 'Report ready',
    failed: 'Report failed',
    download: 'DOWNLOAD',
    caption: '#{id} · {detail}',
  },
}
