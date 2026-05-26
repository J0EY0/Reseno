import { getMessagesSync, getSystemLocale } from '@/i18n'
import { loadLocalePreference } from '@/lib/workspace-storage'

export function resolveApiMessage(messageKey: string, fallbackKey = 'REQUEST_FAILED') {
  const locale = loadLocalePreference() ?? getSystemLocale()
  const messages = getMessagesSync(locale)
  const apiMessages = messages.apiMessages as Record<string, string>

  return apiMessages[messageKey] ?? apiMessages[fallbackKey] ?? messageKey
}
