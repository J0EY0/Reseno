import { locales, type Locale } from '@/i18n'

const localePreferenceKey = 'resumate-locale'

export function loadLocalePreference() {
  if (typeof window === 'undefined') {
    return null
  }

  const value = window.localStorage.getItem(localePreferenceKey)
  return locales.includes(value as Locale) ? (value as Locale) : null
}

export function saveLocalePreference(locale: Locale) {
  if (typeof window === 'undefined') {
    return
  }

  try {
    window.localStorage.setItem(localePreferenceKey, locale)
  } catch {
    // Ignore storage failures in private mode or quota-limited environments.
  }
}
