import vueI18n from '@intlify/eslint-plugin-vue-i18n'
import vue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

const USE_T_FROM_I18N = "Import `t` from '@/i18n' instead (docs/specs/gui.md, Internationalisation)."
const TEXT_ATTRIBUTES = [
  'title', 'aria-label', 'aria-description', 'aria-placeholder', 'aria-roledescription', 'aria-valuetext',
  'label', 'placeholder', 'hint', 'caption', 'alt', 'prefix', 'suffix',
  'message', 'empty-message', 'error-message', 'display-value',
]
const BOUND_TEXT = `VAttribute[directive=true][key.argument.name=/^(${TEXT_ATTRIBUTES.join('|')})$/]`
const RAW_TEXT_IN_BINDING_MESSAGE = 'Raw text in a bound attribute: use t(...) from @/i18n (docs/specs/gui.md, Internationalisation).'
const BOUND_TEXT_SELECTORS = [
  `${BOUND_TEXT} VExpressionContainer > Literal[value=/[A-Za-z]/]`,
  `${BOUND_TEXT} ConditionalExpression > Literal[value=/[A-Za-z]/]`,
  `${BOUND_TEXT} LogicalExpression > Literal[value=/[A-Za-z]/]`,
  `${BOUND_TEXT} TemplateElement[value.raw=/[A-Za-z]/]`,
].map((selector) => ({ selector, message: RAW_TEXT_IN_BINDING_MESSAGE }))
const I18N_API_SELECTORS = [
  { selector: 'Identifier[name="$t"]', message: USE_T_FROM_I18N },
  { selector: 'Identifier[name="useI18n"]', message: USE_T_FROM_I18N },
]

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', '.quasar/**', 'src/api/**'] },
  ...vue.configs['flat/base'],
  ...vueI18n.configs['flat/base'],
  {
    files: ['src/**/*.ts'],
    languageOptions: { parser: tseslint.parser },
  },
  {
    files: ['src/**/*.vue'],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
    rules: {
      '@intlify/vue-i18n/no-raw-text': [
        'error',
        { ignorePattern: '^[\\p{P}\\p{S}\\p{N}\\s]*$', attributes: { '/.+/': TEXT_ATTRIBUTES } },
      ],
    },
  },
  {
    files: ['src/**/*.{vue,ts}'],
    ignores: ['src/i18n/**', 'src/boot/**'],
    rules: {
      'no-restricted-imports': ['error', { paths: [{ name: 'vue-i18n', importNames: ['useI18n'], message: USE_T_FROM_I18N }] }],
    },
  },
  {
    files: ['src/**/*.{vue,ts}'],
    ignores: ['src/i18n/**', 'src/boot/**'],
    rules: { 'no-restricted-syntax': ['error', ...I18N_API_SELECTORS] },
  },
  {
    files: ['src/**/*.vue'],
    ignores: ['src/i18n/**', 'src/boot/**'],
    rules: { 'vue/no-restricted-syntax': ['error', ...I18N_API_SELECTORS, ...BOUND_TEXT_SELECTORS] },
  },
)
