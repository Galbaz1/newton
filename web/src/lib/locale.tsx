import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

/** Add a locale here, its label below, and each `text` entry at the call site. */
export type Locale = 'en' | 'nl'

export const localeNames: Record<Locale, string> = { en: 'English', nl: 'Nederlands' }

type Text = Record<Locale, string>

export function localized(locale: Locale, value: Text): string {
  return value[locale]
}

const LocaleContext = createContext<{ locale: Locale; setLocale: (locale: Locale) => void }>({
  locale: 'en',
  setLocale: () => undefined,
})

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>('en')

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  return <LocaleContext.Provider value={{ locale, setLocale }}>{children}</LocaleContext.Provider>
}

export function useLocale() {
  const { locale, setLocale } = useContext(LocaleContext)
  return { locale, setLocale, text: (value: Text) => localized(locale, value) }
}
