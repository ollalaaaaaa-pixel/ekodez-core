import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import DashboardPage from './DashboardPage'

const jsonResponse = (body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))

const dashboard = {
  revenue: '10000.00',
  expenses: '2500.00',
  profit: '7500.00',
  margin_pct: '75.00',
  total_leads: 4,
  closed_leads: 2,
  conversion_rate: '50.00',
  average_check: '5000.00',
  best_day: { date: '2026-08-20', revenue: '7000.00' },
  top_objects: [{ object_id: 1, name: 'СК Ворон', revenue: '7000.00' }],
  top_services: [{ category: 'Дезинсекция', revenue: '8000.00' }],
  unassigned_revenue: '3000.00',
  daily: [
    { date: '2026-08-19', revenue: '3000.00', expenses: '500.00', profit: '2500.00' },
    { date: '2026-08-20', revenue: '7000.00', expenses: '2000.00', profit: '5000.00' },
  ],
}

describe('Dashboard screen', () => {
  beforeEach(() => vi.restoreAllMocks())

  test('shows KPI, daily chart and rankings with linked-operations label', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => jsonResponse(dashboard))
    render(<DashboardPage />)

    expect(await screen.findByText(/10.000/)).toBeTruthy()
    expect(screen.getAllByText(/7.500/).length).toBeGreaterThan(0)
    expect(screen.getByText('Конверсия')).toBeTruthy()
    expect(screen.getByText('Лучший день')).toBeTruthy()
    expect(screen.getByText(/20\.08\.2026 · 7.000 ₽/)).toBeTruthy()
    expect(screen.getByRole('img', { name: 'График выручки и прибыли по дням' })).toBeTruthy()
    expect(screen.getByText('СК Ворон')).toBeTruthy()
    expect(screen.getByText('Топ объектов — по привязанным операциям')).toBeTruthy()
    expect(screen.getByText('Дезинсекция')).toBeTruthy()
    expect(screen.getByText(/Не привязано к объектам: 3 000 ₽/)).toBeTruthy()
  })

  test('prompts to link finance incomes when object ranking is empty', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      jsonResponse({ ...dashboard, top_objects: [] }),
    )
    render(<DashboardPage />)

    expect(
      await screen.findByText('Привяжите доходы к объектам в „Финансах“'),
    ).toBeTruthy()
  })
})
