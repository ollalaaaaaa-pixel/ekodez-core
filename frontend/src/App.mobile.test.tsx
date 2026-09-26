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
    if (url.includes('/api/auth/session')) body = { authenticated: true, role: 'owner' }
    if (url.includes('/api/gnom/overview')) body = { settings: { weekly_enabled: false, warranty_days: null }, runs: [], expenses: [], candidates: [], analytics: { aggregators: [], revenue_by_month: {}, average_check: null, lead_time_hours: null, rescheduled: 0 } }
    if (url.includes('/api/day?')) body = { entries: [], categories: [], totals: { income: '0.00', expense: '0.00' } }
    if (url.includes('/api/finance/summary')) body = { income: '0.00', expense: '0.00', balance: '0.00' }
    if (url.endsWith('/health')) body = { status: 'ok' }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  })
  const { container } = render(<App />)
  await waitFor(() => expect(container.querySelector('.ant-layout-sider-zero-width-trigger')).toBeTruthy())
  fireEvent.click(container.querySelector('.ant-layout-sider-zero-width-trigger')!)
  fireEvent.click(await screen.findByText('История Гном'))
  await waitFor(() => expect(container.querySelector('.ant-layout-sider-collapsed')).toBeTruthy())
})

test('opens the exact lead selected from the daily plan', async () => {
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
    if (url.includes('/api/auth/session')) body = { authenticated: true, role: 'owner' }
    if (url.includes('/api/day/action-plan')) body = {
      date: '2026-09-25', role: 'owner', counts: { lead_overdue: 1, lead_today: 0 },
      items: [{ kind: 'lead', id: 17, due_date: '2026-09-24', status: 'new', urgency: 'overdue', masked_label: 'Заявка #17', target: { screen: 'leads', kind: 'lead', id: 17 } }],
    }
    if (url.includes('/api/day?')) body = { income_total: '0.00', expense_total: '0.00', balance: '0.00', categories: [], entries: [] }
    if (url.endsWith('/health')) body = { status: 'ok' }
    if (url.endsWith('/api/leads')) body = [{ id: 17, source: 'telegram', status: 'new', amount: '0.00', execution_date: '2026-09-24', performed_by: 'Алексей', client_name: 'ТЕСТ', phone: '***', address: '***', category: null, object_id: null }]
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  })
  const { container } = render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'Открыть заявку #17' }))
  await waitFor(() => expect(container.querySelector('[data-testid="lead-mobile-card"]')?.getAttribute('data-selected')).toBe('true'))
})

test('opens all overdue leads from plan without unrelated rows', async () => {
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
    if (url.includes('/api/auth/session')) body = { authenticated: true, role: 'owner' }
    if (url.includes('/api/day/action-plan?all=true')) body = { group_ids: { lead: [17] } }
    else if (url.includes('/api/day/action-plan')) body = {
      date: '2026-09-25', role: 'owner', counts: { lead_overdue: 6, lead_today: 0 },
      items: [{ kind: 'lead', id: 17, due_date: '2026-09-24', status: 'new', urgency: 'overdue', masked_label: 'Заявка #17', target: { screen: 'leads', kind: 'lead', id: 17 } }],
    }
    if (url.includes('/api/day?')) body = { income_total: '0.00', expense_total: '0.00', balance: '0.00', categories: [], entries: [] }
    if (url.endsWith('/health')) body = { status: 'ok' }
    if (url.endsWith('/api/leads')) body = [17, 99].map(id => ({
      id, source: 'telegram', status: 'new', amount: '0.00', execution_date: '2026-09-24',
      performed_by: 'Алексей', client_name: 'ТЕСТ', phone: '***', address: '***', category: null, object_id: null,
    }))
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  })
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'Заявки: 6 · Все' }))
  expect(await screen.findByText('Заявки из плана: 1')).toBeTruthy()
  expect(screen.queryByText('Заявка #99')).toBeNull()
})
