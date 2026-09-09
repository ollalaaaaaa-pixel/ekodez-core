type DayEntryCandidate = {
  kind: 'income' | 'expense'
  category: string
  marketingSource: string
  amount: number | null
}

export const validateDayEntry = (draft: DayEntryCandidate): string | null => {
  if (!draft.category) return 'Выберите категорию'
  if (draft.kind === 'expense' && draft.category === 'Реклама' && !draft.marketingSource) {
    return 'Выберите источник рекламы'
  }
  if (!draft.amount || draft.amount <= 0) return 'Введите сумму больше нуля'
  return null
}
