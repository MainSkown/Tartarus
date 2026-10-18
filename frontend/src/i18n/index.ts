import { createI18n, I18nT as LooseI18nT } from 'vue-i18n'
import enUS, { datetimeFormats, numberFormats } from './en-US'

export type MessageSchema = typeof enUS
type LeafPaths<Tree, Prefix extends string = ''> = {
  [Name in keyof Tree & string]: Tree[Name] extends string ? `${Prefix}${Name}` : LeafPaths<Tree[Name], `${Prefix}${Name}.`>
}[keyof Tree & string]

/** Every message the en-US catalogue defines, as its dotted path. */
export type MessageKey = LeafPaths<MessageSchema>
export type NumberFormatKey = keyof typeof numberFormats
export type DatetimeFormatKey = keyof typeof datetimeFormats

type NamedValues = Record<string, unknown>

// vue-i18n types its keys as `Key extends string | ResourceKeys`, which autocompletes but accepts any
// string; narrowing them to MessageKey here is what makes an unknown key a vue-tsc error.
interface Translate {
  (key: MessageKey): string
  (key: MessageKey, count: number): string
  (key: MessageKey, named: NamedValues): string
  (key: MessageKey, named: NamedValues, count: number): string
}

export const i18n = createI18n({
  legacy: false,
  locale: 'en-US',
  messages: { 'en-US': enUS },
  numberFormats: { 'en-US': numberFormats },
  datetimeFormats: { 'en-US': datetimeFormats },
})

export const t = i18n.global.t as Translate
export const n = i18n.global.n as (value: number, format: NumberFormatKey) => string
export const d = i18n.global.d as (value: Date | number, format: DatetimeFormatKey) => string
export const I18nT = LooseI18nT as typeof LooseI18nT & (new () => { $props: { keypath: MessageKey } })
