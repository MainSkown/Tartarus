import { config } from '@vue/test-utils'
import { i18n } from '@/i18n'

// @vue/test-utils concatenates these with the plugins each mount passes, so no test installs the catalogue itself.
config.global.plugins = [i18n]
