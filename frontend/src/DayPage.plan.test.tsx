import { afterEach, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import DayPage from './DayPage'

afterEach(() => vi.restoreAllMocks())

test('plan failure does not hide the financial diary', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/api/day/action-plan')) return Promise.resolve(new Response('', { status: 503 }))
    if (url.includes('/api/day?')) return Promise.resolve(new Response(JSON.stringify({ income_total: '0.00', expense_total: '0.00', balance: '0.00', categories: [], entries: [] }), { status: 200 }))
    if (url.endsWith('/health')) return Promise.resolve(new Response(JSON.stringify({ telegram: 'stopped' }), { status: 200 }))
    if (url.includes('/api/finance/summary')) return Promise.resolve(new Response(JSON.stringify({ review_count: 0 }), { status: 200 }))
    return Promise.resolve(new Response('[]', { status: 200 }))
  })
  render(<DayPage onNavigate={vi.fn()} onOpen={vi.fn()} />)
  expect(await screen.findByText('Не удалось загрузить план')).toBeTruthy()
  expect(screen.getByText('ИТОГ ДНЯ')).toBeTruthy()
})
