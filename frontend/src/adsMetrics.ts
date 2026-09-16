import type { Dayjs } from 'dayjs'

export function metricsUrl(start: Dayjs, end: Dayjs) {
  return `/api/ads/metrics?start=${start.format('YYYY-MM-DD')}&end=${end.format('YYYY-MM-DD')}`
}

const reasonLabels: Record<string, string> = {
  no_spend: 'Нет данных о расходах',
  no_income_transactions: 'Нет оплат за период',
  no_attributed_leads: 'Нет атрибутированных лидов',
}

export function metricValue(value: string | null, reason: string | null) {
  return value ?? reasonLabels[reason ?? ''] ?? 'Нет данных'
}
