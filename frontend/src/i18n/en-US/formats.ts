// Same output as `toLocaleString('en-US')`: grouped thousands, no fixed decimals.
export const numberFormats = {
  count: { style: 'decimal', useGrouping: true },
} as const

// Every named format set here must carry `timeZone: 'UTC'`: the app shows instants in UTC for every viewer.
export const datetimeFormats = {} as const
