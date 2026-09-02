import { useEffect, useState } from 'react'

import {
  getLoadedMessages,
  loadMessages,
  type AppMessages,
  type Locale,
} from '@/i18n'

export function useLocalizedMessages(locale: Locale | null) {
  const [state, setState] = useState<{
    locale: Locale | null
    messages: AppMessages | null
  }>(() => ({
    locale,
    messages: locale ? getLoadedMessages(locale) : null,
  }))

  useEffect(() => {
    let active = true

    if (!locale) {
      return () => {
        active = false
      }
    }

    void loadMessages(locale).then((messages) => {
      if (active) {
        setState({ locale, messages })
      }
    })

    return () => {
      active = false
    }
  }, [locale])

  if (!locale) {
    return null
  }

  return getLoadedMessages(locale) ??
    (state.locale === locale ? state.messages : null)
}
