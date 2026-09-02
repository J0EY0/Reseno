import enMessages from './locales/en.json'

export const locales = ['zh', 'en'] as const
export type Locale = (typeof locales)[number]
export type AppMessages = typeof enMessages

export const defaultLocale: Locale = 'en'
export const defaultMessages: AppMessages = enMessages

const messageCache: Partial<Record<Locale, AppMessages>> = {
  en: enMessages,
}
const messageLoadPromises: Partial<Record<Locale, Promise<AppMessages>>> = {}

const localeLoaders: Record<Locale, () => Promise<AppMessages>> = {
  en: () => Promise.resolve(enMessages),
  zh: () => import('./locales/zh.json').then((module) => module.default),
}

export function getMessagesSync(locale: Locale) {
  // Non-default callers must await loadMessages first; this synchronous API is
  // intentionally limited to the bootstrap catalog and an error fallback.
  return messageCache[locale] ?? defaultMessages
}

export function getLoadedMessages(locale: Locale): AppMessages | null {
  return messageCache[locale] ?? null
}

export function loadMessages(locale: Locale): Promise<AppMessages> {
  const cachedMessages = messageCache[locale]
  if (cachedMessages) {
    return Promise.resolve(cachedMessages)
  }

  const pendingLoad = messageLoadPromises[locale]
  if (pendingLoad) {
    return pendingLoad
  }

  const nextLoad = localeLoaders[locale]()
    .then((messages) => {
      messageCache[locale] = messages
      return messages
    })
    .finally(() => {
      delete messageLoadPromises[locale]
    })

  messageLoadPromises[locale] = nextLoad
  return nextLoad
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
