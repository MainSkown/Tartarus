export default {
  zoom: {
    group: 'Zoom',
    fit: 'FIT',
    oneMinute: '1M',
    tenSeconds: '10S',
    oneSecond: '1S',
  },
  tab: {
    emptyMessage: 'no events in this analysis',
    unknownError: 'unknown error',
  },
  canvas: {
    ariaLabel: "Timeline of the analysis's events, one lane per category",
    ariaDescription: 'Arrow left and right pan, plus and minus zoom, 0 fits the whole run, Home and End jump to the start and the end, Escape clears the selected range',
    loading: 'Loading the range',
    empty: '> no events in this range',
  },
  gutter: {
    detections: 'DETECTIONS',
    clock: 'UTC',
  },
  laneBars: {
    ariaLabel: 'Events by lane',
  },
  lane: {
    process: 'PROCESS',
    file: 'FILE',
    registry: 'REGISTRY',
    network: 'NETWORK',
    memory: 'MEMORY',
    api: 'API',
  },
  span: {
    milliseconds: '{value} ms',
    seconds: '{value} s',
  },
  range: {
    visible: '{start} - {end} UTC · {span}',
    brushed: '{start} - {end} · {span}',
  },
  count: {
    thousands: '{value}k',
  },
  tooltip: {
    timeRange: '{start} - {end}',
    destination: '{address} ({domain})',
    pid: '({pid})',
    events: '{count} {lane} event | {count} {lane} events',
    more: '+{count} more',
    detection: 'detection',
    row: {
      time: 'TIME',
      process: 'PROCESS',
      api: 'API',
      file: 'FILE',
      key: 'KEY',
      url: 'URL',
      dns: 'DNS',
      dest: 'DEST',
      action: 'ACTION',
      span: 'SPAN',
      ruleset: 'RULESET',
    },
    hint: {
      open: 'click to open',
      zoomIn: 'click to zoom in',
      openFirst: 'click to open the first',
    },
  },
}
