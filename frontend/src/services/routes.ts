import type { Route } from '@/api'

// The backend still accepts Tor, VPN, WireGuard and SOCKS5, but no tunnel is built yet, so
// neither the submit dialog nor Settings may offer them (gui spec: shown only once configured).
export const BUILT_ROUTES: Route[] = ['inetsim', 'none', 'drop', 'internet']
