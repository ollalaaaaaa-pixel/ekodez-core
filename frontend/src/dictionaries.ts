export const INCOME_CATEGORIES = [
  'Химчистка',
  'Дезинсекция',
  'Дератизация',
  'Дезинфекция',
  'Обработка от клещей',
  'Клининг',
  'Юридические клиенты',
  'Доход от агрегаторов',
  'Плесень',
  'Другие работы',
] as const

export const LEAD_SOURCES = [
  { value: 'telegram', label: 'Telegram-бот' },
  { value: 'aggregators', label: 'Агрегаторы' },
  { value: 'other', label: 'Другое' },
] as const

export const LEAD_SOURCE_LABELS = Object.fromEntries(
  LEAD_SOURCES.map(({ value, label }) => [value, label]),
) as Record<string, string>
