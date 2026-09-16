import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

afterEach(() => vi.restoreAllMocks())

test('mobile navigation collapses after choosing a section', async () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query.includes('max-width'), media: query, onchange: null,
      addListener: vi.fn(), removeListener: vi.fn(),
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    })),
  })
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input)
    let body: unknown = []
    if (url.includes('/api/gnom/overview')) body = { settings: { weekly_enabled: false, warranty_days: null }, runs: [], expenses: [], candidates: [], analytics: { aggregators: [], revenue_by_month: {}, average_check: null, lead_time_hours: null, rescheduled: 0 } }
    if (url.includes('/api/day?')) body = { entries: [], categories: [], totals: { income: '0.00', expense: '0.00' } }
    if (url.includes('/api/finance/summary')) body = { income: '0.00', expense: '0.00', balance: '0.00' }
    if (url.endsWith('/health')) body = { status: 'ok' }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  })
  const { container } = render(<App />)
  const trigger = await waitFor(() => container.querySelector('.ant-layout-sider-zero-width-trigger'))
  expect(trigger).toBeTruthy()
  fireEvent.click(trigger!)
  fireEvent.click(await screen.findByText('История Гном'))
  await waitFor(() => expect(container.querySelector('.ant-layout-sider-collapsed')).toBeTruthy())
})
