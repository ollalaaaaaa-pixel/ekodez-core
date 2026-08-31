import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Modal } from 'antd'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import LeadsPage from './LeadsPage'

const maskedLead = {
  id: 1,
  source: 'telegram',
  category: null,
  external_id: '700001',
  order_at: '2026-08-23T12:00:00',
  client_name: 'Артём',
  phone: '8921***5000',
  address: 'г. Архангельск, ***',
  area: null,
  reason: 'тараканы',
  comment: null,
  amount_note: null,
  contract: null,
  partner: null,
  status: 'new',
  amount: '0.00',
  execution_date: '2026-08-31',
  object_id: null,
  performed_by: 'Артём',
}

const jsonResponse = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

describe('Lead PII reveal', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })))
  })
  afterEach(() => {
    cleanup()
    Modal.destroyAll()
    document.body.replaceChildren()
  })

  test('shows masks by default and reveals one lead after confirmation', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => jsonResponse([maskedLead]))
      .mockImplementationOnce(() =>
        jsonResponse({
          ...maskedLead,
          client_name: 'Котлов Артём Васильевич',
          phone: '89214725000',
          address: 'г. Архангельск, ул. Ленина, 10, кв. 5',
        }),
      )
    const user = userEvent.setup()

    render(<LeadsPage />)
    expect(await screen.findByText('8921***5000')).toBeTruthy()
    expect(screen.queryByText('89214725000')).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Показать полностью' }))
    expect(
      (await screen.findAllByText('Раскрыть персональные данные этой заявки?')).length,
    ).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: 'Да, показать' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://127.0.0.1:8000/api/leads/1?show_pii=true',
    )
    expect(await screen.findByText('89214725000')).toBeTruthy()
    expect(screen.getByText('г. Архангельск, ул. Ленина, 10, кв. 5')).toBeTruthy()
  }, 15_000)

  test('accepts an aggregators lead with mold service and optional amount', async () => {
    const createdLead = {
      ...maskedLead,
      id: 2,
      source: 'aggregators',
      category: 'Плесень',
      client_name: 'ТЕСТ',
      phone: '8921***5000',
    }
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => jsonResponse([]))
      .mockImplementationOnce(() => jsonResponse(createdLead))
    const user = userEvent.setup()

    render(<LeadsPage />)
    await user.click(await screen.findByRole('button', { name: /Принять заявку/ }))
    await user.click(screen.getByLabelText('Источник'))
    await user.click(await screen.findByText('Агрегаторы'))
    await user.click(screen.getByLabelText('Услуга'))
    await user.click(await screen.findByText('Плесень'))
    await user.type(screen.getByLabelText('Имя клиента'), 'ТЕСТ Клиент')
    await user.type(screen.getByLabelText('Телефон'), '89214725000')
    await user.type(screen.getByLabelText('Адрес'), 'г. Архангельск, ТЕСТ адрес')
    await user.click(screen.getByRole('button', { name: 'Сохранить заявку' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const [, options] = fetchMock.mock.calls[1]
    const body = JSON.parse(String(options?.body))
    expect(body.source).toBe('aggregators')
    expect(body.category).toBe('Плесень')
    expect(body.text).not.toContain('Сумма:')
    expect(await screen.findByText('Агрегаторы')).toBeTruthy()
    expect(await screen.findByText('Плесень')).toBeTruthy()
    expect(screen.getByText('8921***5000')).toBeTruthy()
  }, 15_000)

  test('edits operational fields through PATCH and labels object exactly', async () => {
    const object = { id: 7, name: 'ТЕСТ объект' }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) return jsonResponse([object])
      if (url.endsWith('/api/leads') && !init?.method) return jsonResponse([maskedLead])
      if (url.endsWith('/api/leads/1') && init?.method === 'PATCH') {
        return jsonResponse({ ...maskedLead, ...JSON.parse(String(init.body)) })
      }
      return jsonResponse([])
    })
    const user = userEvent.setup()
    render(<LeadsPage />)

    await user.click(await screen.findByRole('button', { name: 'Редактировать' }))
    expect(screen.getByLabelText('Объект')).toBeTruthy()
    await user.clear(screen.getByLabelText('Сумма'))
    await user.type(screen.getByLabelText('Сумма'), '2500')
    await user.clear(screen.getByLabelText('Дата обработки'))
    await user.type(screen.getByLabelText('Дата обработки'), '2026-09-01')
    await user.click(screen.getByRole('button', { name: 'Сохранить изменения' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/leads/1',
      expect.objectContaining({ method: 'PATCH' }),
    ))
    const call = fetchMock.mock.calls.find(([url, init]) =>
      String(url).endsWith('/api/leads/1') && init?.method === 'PATCH')
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      amount: '2500.00',
      execution_date: '2026-09-01',
      category: null,
      object_id: null,
      performed_by: 'Артём',
    })
  }, 15_000)

  test('today filter and mobile cards include only due active leads', async () => {
    vi.setSystemTime(new Date('2026-08-31T10:00:00+03:00'))
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: query.includes('767px'), media: query,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })))
    const variants = [
      { ...maskedLead, id: 1, execution_date: '2026-08-30', status: 'new' },
      { ...maskedLead, id: 2, execution_date: '2026-08-31', status: 'in_work' },
      { ...maskedLead, id: 3, execution_date: '2026-09-01', status: 'new' },
      { ...maskedLead, id: 4, execution_date: '2026-08-31', status: 'done' },
      { ...maskedLead, id: 5, execution_date: null, status: 'new' },
    ]
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) =>
      String(input).endsWith('/api/objects') ? jsonResponse([]) : jsonResponse(variants))
    const user = userEvent.setup()
    render(<LeadsPage />)
    await user.click(await screen.findByText('Сегодня'))

    expect(await screen.findAllByTestId('lead-mobile-card')).toHaveLength(2)
    expect(screen.queryByTestId('lead-desktop-table')).toBeNull()
    expect(screen.getAllByText('8921***5000')).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Редактировать' })).toHaveLength(2)
    vi.useRealTimers()
  })
})
