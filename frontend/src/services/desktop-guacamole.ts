import type * as Guacamole from 'guacamole-common-js'

export type GuacamoleModule = typeof Guacamole

/** The library is a global-style bundle whose ES build has only a default export; it is loaded when a desktop is first wanted. */
export async function loadGuacamole(): Promise<GuacamoleModule> {
  const loaded = (await import('guacamole-common-js')) as unknown as { default: GuacamoleModule }
  return loaded.default
}
