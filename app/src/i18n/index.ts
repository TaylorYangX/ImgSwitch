import { createI18n } from 'vue-i18n'
import en from './en.json'
import zhCN from './zh-CN.json'

export type Language = 'en' | 'zh-CN'

export const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: { en, 'zh-CN': zhCN },
})

export function setLanguage(language: Language): void {
  i18n.global.locale.value = language
  document.documentElement.lang = language
}
