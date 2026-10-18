import js from '@eslint/js'
import quasar from '@quasar/app-vite/eslint'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import vue from 'eslint-plugin-vue'
import i18nRules from './eslint.i18n-rules.js'

export default tseslint.config(
  ...quasar.configs.recommended(),
  // src/api/ is @hey-api/openapi-ts output (F7), never hand-edited: see backend spec "API
  // client" and the gui spec's "Frontend structure" table, which both put it at ./src/api
  // rather than the ./src/api/generated the gui spec's intro bullet mentions.
  { ignores: ['dist/**', 'node_modules/**', '.quasar/**', 'src/api/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
  },
  ...i18nRules,
  {
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },
)
