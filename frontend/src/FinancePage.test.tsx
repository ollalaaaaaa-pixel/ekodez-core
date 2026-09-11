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
      lead_id: null,
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
      object_id: 1, object_name: 'СК Ворон', lead_id: null,
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

  test('edits an operation and opens its linked lead card', async () => {
    const transaction = {
      id: 9,
      source: 'lead_auto',
      operation_date: '2026-08-20',
      amount: '5000.00',
      currency: 'RUB',
      counterparty: null,
      description: 'Автодоход',
      category: 'Другие работы',
      kind: 'income',
      review_required: false,
      object_id: null,
      object_name: null,
      lead_id: 11,
    }
    const linkedLead = {
      id: 11,
      client_name: 'ТЕСТ клиент',
      phone: '8921***5000',
      address: 'г. Архангельск, ***',
      category: 'Другие работы',
      amount: '5000.00',
      execution_date: '2026-08-20',
      performed_by: 'Артём',
      status: 'done',
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) return jsonResponse([])
      if (url.endsWith('/api/finance/summary')) {
        return jsonResponse({ income: '5000.00', expense: '0.00', review_count: 0 })
      }
      if (url.includes('/api/analytics/channels')) {
        return jsonResponse({ period_total: '5000.00', channels: [] })
      }
      if (url.endsWith('/api/leads/11')) return jsonResponse(linkedLead)
      if (url.endsWith('/api/transactions/9') && init?.method === 'PATCH') {
        return jsonResponse({
          ...transaction,
          ...JSON.parse(String(init.body)),
        })
      }
      return jsonResponse([transaction])
    })
    const user = userEvent.setup()
    render(<FinancePage />)

    await user.click(await screen.findByRole('button', { name: 'Заявка #11' }))
    expect(await screen.findByText('ТЕСТ клиент')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Закрыть карточку заявки' }))

    await user.click(screen.getByRole('button', { name: 'Редактировать' }))
    await user.clear(screen.getByLabelText('Дата операции'))
    await user.type(screen.getByLabelText('Дата операции'), '2026-08-19')
    await user.click(screen.getByLabelText('Категория'))
    await user.click(await screen.findByText('Дезинсекция'))
    await user.clear(screen.getByLabelText('Комментарий'))
    await user.type(screen.getByLabelText('Комментарий'), 'ТЕСТ-правка')
    await user.click(screen.getByRole('button', { name: 'Сохранить операцию' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/transactions/9',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          operation_date: '2026-08-19',
          category: 'Дезинсекция',
          description: 'ТЕСТ-правка',
        }),
      }),
    ))
    expect((await screen.findAllByText('ТЕСТ-правка')).length).toBeGreaterThan(0)
  }, 20_000)

  test('edits date and comment without category for an unknown operation', async () => {
    const transaction = {
      id: 12,
      source: 'telegram',
      operation_date: '2026-08-20',
      amount: '0.00',
      currency: 'RUB',
      counterparty: null,
      description: null,
      category: null,
      kind: 'unknown',
      review_required: false,
      object_id: null,
      object_name: null,
      lead_id: null,
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) return jsonResponse([])
      if (url.endsWith('/api/finance/summary')) {
        return jsonResponse({ income: '0.00', expense: '0.00', review_count: 0 })
      }
      if (url.includes('/api/analytics/channels')) {
        return jsonResponse({ period_total: '0.00', channels: [] })
      }
      if (url.endsWith('/api/transactions/12') && init?.method === 'PATCH') {
        return jsonResponse({ ...transaction, ...JSON.parse(String(init.body)) })
      }
      return jsonResponse([transaction])
    })
    const user = userEvent.setup()
    render(<FinancePage />)

    await user.click(await screen.findByRole('button', { name: 'Редактировать' }))
    expect(screen.queryByLabelText('Категория')).toBeNull()
    await user.clear(screen.getByLabelText('Дата операции'))
    await user.type(screen.getByLabelText('Дата операции'), '2026-08-19')
    await user.type(screen.getByLabelText('Комментарий'), 'ТЕСТ-без категории')
    await user.click(screen.getByRole('button', { name: 'Сохранить операцию' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/transactions/12',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          operation_date: '2026-08-19',
          description: 'ТЕСТ-без категории',
        }),
      }),
    ))
  }, 15_000)

  test('shows and corrects the source of an advertising expense', async () => {
    const transaction = {
      id: 13, source: 'manual', operation_date: '2026-09-08', amount: '6000.00',
      currency: 'RUB', counterparty: null, description: 'Кампания',
      category: 'Реклама', marketing_source: null, kind: 'expense',
      review_required: false, object_id: null, object_name: null, lead_id: null,
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) return jsonResponse([])
      if (url.endsWith('/api/expense-categories')) {
        return jsonResponse([{ id: 1, name: 'Реклама' }])
      }
      if (url.endsWith('/api/finance/summary')) {
        return jsonResponse({ income: '0.00', expense: '6000.00', review_count: 0 })
      }
      if (url.includes('/api/analytics/channels')) {
        return jsonResponse({ period_total: '0.00', channels: [] })
      }
      if (url.endsWith('/api/transactions/13') && init?.method === 'PATCH') {
        return jsonResponse({ ...transaction, ...JSON.parse(String(init.body)) })
      }
      return jsonResponse([transaction])
    })
    const user = userEvent.setup()
    render(<FinancePage />)

    expect(await screen.findByText('Источник: не указан')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Редактировать' }))
    await user.click(screen.getByLabelText('Источник рекламы'))
    await user.click(await screen.findByText('ВКонтакте'))
    await user.click(screen.getByRole('button', { name: 'Сохранить операцию' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/transactions/13',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          operation_date: '2026-09-08',
          category: 'Реклама',
          description: 'Кампания',
          marketing_source: 'vk',
        }),
      }),
    ))
  }, 20_000)
})
