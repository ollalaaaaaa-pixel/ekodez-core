import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FinancePage from './FinancePage'

const jsonResponse = (body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))

describe('Finance object linking', () => {
  beforeEach(() => vi.restoreAllMocks())

  test('links an existing imported income to an object without guessing', async () => {
    const transaction = {
      id: 7,
      source: 'tbank',
      operation_date: '2026-08-20',
      amount: '5000.00',
      currency: 'RUB',
      counterparty: 'Контрагент',
      description: 'Оплата',
      category: 'Юридические клиенты',
      kind: 'income',
      review_required: false,
      object_id: null,
      object_name: null,
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) {
        return jsonResponse([{ id: 1, name: 'СК Ворон' }])
      }
      if (url.endsWith('/api/transactions/7/object') && init?.method === 'PATCH') {
        return jsonResponse({ ...transaction, object_id: 1, object_name: 'СК Ворон' })
      }
      if (url.endsWith('/api/finance/summary')) {
        return jsonResponse({ income: '5000.00', expense: '0.00', review_count: 0 })
      }
      if (url.includes('/api/analytics/channels')) {
        return jsonResponse({ period_total: '5000.00', channels: [] })
      }
      return jsonResponse([transaction])
    })
    const user = userEvent.setup()

    render(<FinancePage />)
    await user.click(await screen.findByRole('button', { name: 'Привязать объект' }))
    await user.click(screen.getByRole('combobox', { name: 'Объект' }))
    await user.click(await screen.findByText('СК Ворон'))
    await user.click(screen.getByRole('button', { name: 'Сохранить привязку' }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([input]) =>
        String(input).endsWith('/api/transactions/7/object'),
      )
      expect(call?.[1]).toMatchObject({
        method: 'PATCH',
        body: JSON.stringify({ object_id: 1 }),
      })
    })
  }, 15_000)

  test('labels a linked income as change object and uses the same modal', async () => {
    const transaction = {
      id: 8, source: 'manual', operation_date: '2026-08-20', amount: '7000.00',
      currency: 'RUB', counterparty: null, description: 'ТЕСТ',
      category: 'Плесень', kind: 'income', review_required: false,
      object_id: 1, object_name: 'СК Ворон',
    }
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) return jsonResponse([{ id: 1, name: 'СК Ворон' }])
      if (url.endsWith('/api/finance/summary')) return jsonResponse({ income: '7000.00', expense: '0.00', review_count: 0 })
      if (url.includes('/api/analytics/channels')) return jsonResponse({ period_total: '7000.00', channels: [] })
      return jsonResponse([transaction])
    })
    const user = userEvent.setup()
    render(<FinancePage />)

    await user.click(await screen.findByRole('button', { name: 'Изменить объект' }))
    expect(screen.getAllByText('Изменить объект').length).toBeGreaterThan(1)
  }, 15_000)
})
