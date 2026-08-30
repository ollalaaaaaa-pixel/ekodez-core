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
}

const jsonResponse = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

describe('Lead PII reveal', () => {
  beforeEach(() => vi.restoreAllMocks())
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
})
