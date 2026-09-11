import { describe, expect, test } from 'vitest'
import { validateDayEntry } from './dayEntryValidation'

describe('day entry validation', () => {
  test('requires a marketing source before sending an advertising expense', () => {
    expect(validateDayEntry({
      kind: 'expense', category: 'Реклама', marketingSource: '', amount: 6000,
    })).toBe('Выберите источник рекламы')
  })

  test('accepts a tagged advertising expense', () => {
    expect(validateDayEntry({
      kind: 'expense', category: 'Реклама', marketingSource: 'vk', amount: 6000,
    })).toBeNull()
  })
})
