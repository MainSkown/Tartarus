/** The socket paths of the two desktops the backend tunnels; `resolveWsUrl` makes them absolute. */
export function analysisDesktopPath(analysisId: number): string {
  return `/ws/analyses/${analysisId}/desktop`
}

export function guestDesktopPath(guestName: string): string {
  return `/ws/guests/${encodeURIComponent(guestName)}/desktop`
}
