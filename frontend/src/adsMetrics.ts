import type { Dayjs } from 'dayjs'

export function metricsUrl(start: Dayjs, end: Dayjs) {
  return `/api/ads/metrics?start=${start.format('YYYY-MM-DD')}&end=${end.format('YYYY-MM-DD')}`
}

export function metricValue(value: string | null) {
  return value ?? '—'
}
