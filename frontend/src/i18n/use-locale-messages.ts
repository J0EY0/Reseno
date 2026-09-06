import { useCallback, useEffect, useRef, useState } from 'react'

import {
  defaultLocale,
  defaultMessages,
  getMessagesSync,
  loadMessages,
  type AppMessages,
  type Locale,
} from '@/i18n'

interface LocaleSnapshot {
  locale: Locale
  messages: AppMessages
}

interface LocaleMessagesState {
  canPersistLocale: boolean
  isMessagesReady: boolean
  snapshot: LocaleSnapshot
}

export function useLocaleMessages(initialLocale: Locale) {
  const initialLocaleRef = useRef(initialLocale)
  const activeLocaleRef = useRef(initialLocale)
  const requestIdRef = useRef(0)
  const [state, setState] = useState<LocaleMessagesState>(() => ({
    canPersistLocale: initialLocale === defaultLocale,
    isMessagesReady: initialLocale === defaultLocale,
    snapshot: {
      locale: initialLocale,
      messages: getMessagesSync(initialLocale),
    },
  }))
  const requestLocale = useCallback(
    async (nextLocale: Locale, isInitialRequest = false) => {
      requestIdRef.current += 1
      const requestId = requestIdRef.current

      // Selecting the active locale still invalidates an older pending request.
      if (!isInitialRequest && nextLocale === activeLocaleRef.current) {
        setState((current) =>
          current.canPersistLocale
            ? current
            : { ...current, canPersistLocale: true },
        )
        return true
      }

      return loadMessages(nextLocale)
        .then((nextMessages) => {
          if (requestId !== requestIdRef.current) {
            return false
          }

          activeLocaleRef.current = nextLocale
          setState({
            canPersistLocale: true,
            isMessagesReady: true,
            snapshot: { locale: nextLocale, messages: nextMessages },
          })
          return true
        })
        .catch((error: unknown) => {
          if (requestId !== requestIdRef.current) {
            return false
          }

          console.error(`Failed to load messages for locale "${nextLocale}".`, error)
          if (isInitialRequest) {
            // Keep an unreadable saved locale intact while rendering the known
            // synchronous catalog; a later explicit choice can retry the chunk.
            activeLocaleRef.current = defaultLocale
            setState({
              canPersistLocale: false,
              isMessagesReady: true,
              snapshot: {
                locale: defaultLocale,
                messages: defaultMessages,
              },
            })
          }
          return false
        })
    },
    [],
  )

  useEffect(() => {
    if (initialLocaleRef.current !== defaultLocale) {
      requestLocale(initialLocaleRef.current, true)
    }

    return () => {
      requestIdRef.current += 1
    }
  }, [requestLocale])

  const changeLocale = useCallback(
    (nextLocale: Locale) => requestLocale(nextLocale),
    [requestLocale],
  )

  return {
    ...state.snapshot,
    canPersistLocale: state.canPersistLocale,
    changeLocale,
    isMessagesReady: state.isMessagesReady,
  }
}
