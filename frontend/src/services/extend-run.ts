export const EXTEND_STEP_S = 60
// CAPE's own limit for an interactive task; the backend never moves a deadline past start + this.
export const LONGEST_RUN_S = 20 * 60

export const EXTEND_LABEL = `+${EXTEND_STEP_S}S`

const LONGEST_RUN_MINUTES = LONGEST_RUN_S / 60

export function extendTitle(atLongest: boolean): string {
  return atLongest
    ? `The run is already at its longest (${LONGEST_RUN_MINUTES} minutes)`
    : `Adds ${EXTEND_STEP_S} seconds to the run`
}
