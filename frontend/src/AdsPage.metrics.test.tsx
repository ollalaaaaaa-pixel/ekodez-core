import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'

import { metricsUrl, metricValue } from './adsMetrics'

describe('advertising metric period and nulls', () => {
  it('builds the metrics request from the selected period', () => {
    expect(metricsUrl(dayjs('2026-08-01'), dayjs('2026-08-31'))).toBe(
      '/api/ads/metrics?start=2026-08-01&end=2026-08-31',
    )
  })

  it('shows an explicit reason for unavailable metric values', () => {
    expect(metricValue(null, 'no_spend')).toBe('Нет данных о расходах')
    expect(metricValue(null, 'no_income_transactions')).toBe('Нет оплат за период')
    expect(metricValue(null, 'no_attributed_leads')).toBe('Нет атрибутированных лидов')
    expect(metricValue('125.00', null)).toBe('125.00')
  })
})
