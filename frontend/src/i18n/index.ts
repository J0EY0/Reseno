import enMessages from './locales/en.json'
import zhMessages from './locales/zh.json'

export const locales = ['zh', 'en'] as const
export type Locale = (typeof locales)[number]
export type AppMessages = typeof zhMessages

export const defaultLocale: Locale = 'en'
export const defaultMessages: AppMessages = enMessages

const messageCache: Partial<Record<Locale, AppMessages>> = {
  en: enMessages,
  zh: zhMessages,
}

const localeLoaders: Record<Locale, () => Promise<AppMessages>> = {
  en: async () => enMessages,
  zh: async () => zhMessages,
}

export function getMessagesSync(locale: Locale) {
  return messageCache[locale] ?? defaultMessages
}

export async function loadMessages(locale: Locale) {
  if (messageCache[locale]) {
    return messageCache[locale]
  }

  const messages = await localeLoaders[locale]()
  messageCache[locale] = messages
  return messages
}

export function resolveSupportedLocale(value: string | null | undefined): Locale | null {
  if (!value) {
    return null
  }

  const normalized = value.toLowerCase()

  if (normalized === 'zh' || normalized.startsWith('zh-')) {
    return 'zh'
  }

  if (normalized === 'en' || normalized.startsWith('en-')) {
    return 'en'
  }

  return null
}

export function getSystemLocale(): Locale {
  if (typeof navigator === 'undefined') {
    return defaultLocale
  }

  const candidates = [
    ...(Array.isArray(navigator.languages) ? navigator.languages : []),
    navigator.language,
  ]

  for (const candidate of candidates) {
    const locale = resolveSupportedLocale(candidate)

    if (locale) {
      return locale
    }
  }

  return defaultLocale
}
