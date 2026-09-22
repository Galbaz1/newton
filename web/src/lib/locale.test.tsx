import { describe, expect, it } from 'vitest'
import { localized } from './locale'

describe('localized', () => {
  it('uses English as the initial locale and resolves Dutch when selected', () => {
    const copy = { en: 'Sources', nl: 'Bronnen' }
    expect(localized('en', copy)).toBe('Sources')
    expect(localized('nl', copy)).toBe('Bronnen')
  })
})
