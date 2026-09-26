import { afterEach, expect, test, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import TodayActionPlan from './TodayActionPlan'

afterEach(() => vi.restoreAllMocks())

test('loads safe action cards and opens the selected record', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    date: '2026-09-25', role: 'owner',
    counts: { lead_overdue: 1, lead_today: 0, object_due: 0, inventory_low: 0, document_review: 0, transaction_review: 0 },
    items: [{ kind: 'lead', id: 17, due_date: '2026-09-24', status: 'new', urgency: 'overdue', masked_label: 'Заявка #17', linked_object_due: true, target: { screen: 'leads', kind: 'lead', id: 17 } }],
  }), { status: 200 }))
  const onOpen = vi.fn()
  render(<TodayActionPlan onOpen={onOpen} onNavigate={vi.fn()} />)
  expect(await screen.findByText('Заявка #17')).toBeTruthy()
  expect(screen.getByText('Повторная обработка объекта')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Открыть заявку #17' }))
  expect(onOpen).toHaveBeenCalledWith({ screen: 'leads', kind: 'lead', id: 17 })
})

test('shows retry on independent load failure', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 503 }))
  render(<TodayActionPlan onOpen={vi.fn()} onNavigate={vi.fn()} />)
  expect(await screen.findByText('Не удалось загрузить план')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Повторить' })).toBeTruthy()
})

test('shows an empty state without losing the section', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    date: '2026-09-25', role: 'master',
    counts: { lead_overdue: 0, lead_today: 0, object_due: 0, inventory_low: 0 },
    items: [],
  }), { status: 200 }))
  render(<TodayActionPlan onOpen={vi.fn()} onNavigate={vi.fn()} />)
  expect(await screen.findByText('Срочных дел нет')).toBeTruthy()
})

test('today-only leads retain their section link', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    date: '2026-09-25', role: 'master',
    counts: { lead_overdue: 0, lead_today: 1, object_due: 0, inventory_low: 0 },
    items: [{ kind: 'lead', id: 20, due_date: '2026-09-25', status: 'new', urgency: 'today', masked_label: 'Заявка #20', target: { screen: 'leads', kind: 'lead', id: 20 } }],
  }), { status: 200 }))
  render(<TodayActionPlan onOpen={vi.fn()} onNavigate={vi.fn()} />)
  expect(await screen.findByRole('button', { name: 'Заявки: 1 · Перейти в раздел' })).toBeTruthy()
})

test('counters include due objects as well as leads', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    date: '2026-09-25', role: 'owner',
    counts: { lead_overdue: 1, lead_today: 0, object_overdue: 2, object_today: 1, object_due: 3, inventory_low: 0 },
    items: [{ kind: 'object', id: 4, due_date: '2026-09-24', status: 'active', urgency: 'overdue', masked_label: 'Объект #4', target: { screen: 'objects', kind: 'object', id: 4 } }],
  }), { status: 200 }))
  render(<TodayActionPlan onOpen={vi.fn()} onNavigate={vi.fn()} />)
  expect(await screen.findByText('Объект #4')).toBeTruthy()
  const counters = document.querySelector('.today-plan-counters')?.textContent
  expect(counters).toMatch(/Просрочено\s*3/)
  expect(counters).toMatch(/На сегодня\s*1/)
})

test('excess work opens the complete filtered group', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    date: '2026-09-25', role: 'owner',
    counts: { lead_overdue: 6, lead_today: 0, object_due: 0, inventory_low: 0 },
    items: [{ kind: 'lead', id: 1, due_date: '2026-09-24', status: 'new', urgency: 'overdue', masked_label: 'Заявка #1', target: { screen: 'leads', kind: 'lead', id: 1 } }],
  }), { status: 200 }))
  const onNavigate = vi.fn()
  render(<TodayActionPlan onOpen={vi.fn()} onNavigate={onNavigate} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Заявки: 6 · Все' }))
  expect(onNavigate).toHaveBeenCalledWith('leads', 'lead')
})
