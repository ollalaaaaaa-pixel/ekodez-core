import { render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import MarketingPanel from './MarketingPanel'

afterEach(() => vi.restoreAllMocks())

test('zero leads shows no CPL, payments are not called profit', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    channels: [{source:'vk',label:'ВКонтакте',leads:0,expenses:'6000.00',paid_revenue:'0.00',cpl:null,roas:'0.00'}],
    unassigned_ad_expenses:'500.00',
  })))
  render(<MarketingPanel query="start_date=2026-09-01&end_date=2026-09-08" />)
  const label = await screen.findByText('ВКонтакте')
  const row = label.closest('tr')!
  expect(within(row).getByText('—')).toBeTruthy()
  expect(within(row).getByText('6000.00')).toBeTruthy()
  expect(screen.getByText(/не прибыль и не ROMI/)).toBeTruthy()
  expect(screen.getByText(/без источника: 500.00/)).toBeTruthy()
})

test('denied access is unavailable, not zero performance', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', {status:403}))
  render(<MarketingPanel query="start_date=2026-09-01&end_date=2026-09-08" />)
  expect(await screen.findByText(/показатели недоступны/)).toBeTruthy()
  expect(screen.queryByText('0.00')).toBeNull()
})
