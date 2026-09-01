import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import ObjectsPage from './ObjectsPage'

const objectRow = {
  id: 1,
  name: 'СК Ворон',
  address: 'П. Галушина 21 к.1',
  type: 'gym',
  area_sqm: '200.00',
  contract: {
    id: 1,
    number: '17/08',
    price: '5000.00',
    contract_date: '2026-08-17',
    periodicity: 'monthly',
    service_months: [],
    payment_term_business_days: 5,
    default_ksp: 5,
    default_derat_glue: 5,
    default_baits: 5,
    default_disinsection_glue: 6,
    start_date: null,
    end_date: null,
  },
  risk_points: ['раздевалка'],
  last_treatment_date: '2026-08-01',
  next_treatment_date: '2026-09-01',
  status: 'active',
}

const jsonResponse = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

describe('Objects screen', () => {
  beforeEach(() => vi.restoreAllMocks())

  test('creates a gym object and opens its card with contract and history', async () => {
    let listCalls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith('/api/objects') && init?.method === 'POST') {
        return jsonResponse(objectRow)
      }
      if (url.endsWith('/api/objects/1/treatments')) {
        return jsonResponse([
          {
            id: 7,
            lead_id: null,
            object_id: 1,
            chemicals_used: [],
            performed_at: '2026-08-20T11:00:00',
            performed_by: 'Артём',
            notes: 'Профилактика',
          },
        ])
      }
      if (url.endsWith('/api/objects/1/contract-timeline')) {
        return jsonResponse([])
      }
      listCalls += 1
      return jsonResponse(listCalls === 1 ? [] : [objectRow])
    })
    const user = userEvent.setup()

    render(<ObjectsPage />)
    await user.click(await screen.findByRole('button', { name: /Добавить объект/ }))
    await user.type(screen.getByPlaceholderText('Название объекта'), 'СК Ворон')
    await user.type(screen.getByPlaceholderText('Адрес'), 'П. Галушина 21 к.1')
    await user.type(screen.getByPlaceholderText('Площадь, м²'), '200')
    await user.type(screen.getByPlaceholderText('Номер договора'), '17/08')
    await user.type(screen.getByPlaceholderText('Цена договора, ₽'), '5000')
    await user.click(screen.getByLabelText('Периодичность'))
    await user.click(await screen.findByText('Ежемесячно'))
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    expect(await screen.findByText('СК Ворон')).toBeTruthy()
    expect(screen.getByText('П. Галушина 21 к.1')).toBeTruthy()
    expect(screen.getByText('200.00 м²')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Открыть' }))

    expect(await screen.findByText('Карточка объекта')).toBeTruthy()
    expect(screen.getByText('Договор 17/08')).toBeTruthy()
    expect(screen.getByText(/5\s000,00 ₽\/мес/)).toBeTruthy()
    expect(screen.getByText('раздевалка')).toBeTruthy()
    expect(screen.getByText('01.08.2026')).toBeTruthy()
    expect(screen.getByText('01.09.2026')).toBeTruthy()
    expect(screen.getByText('История обработок')).toBeTruthy()
    expect(await screen.findByText('Профилактика')).toBeTruthy()
    expect(screen.getByText('Документы')).toBeTruthy()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  })

  test('contract price has no default and monthly package exposes required fields', async () => {
    const objectWithoutContract = { ...objectRow, contract: null }
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) return jsonResponse([objectWithoutContract])
      if (url.endsWith('/api/objects/1/treatments')) return jsonResponse([])
      if (url.endsWith('/api/objects/1/contract-timeline')) return jsonResponse([])
      return jsonResponse([])
    })
    const user = userEvent.setup()

    render(<ObjectsPage />)
    await user.click((await screen.findAllByRole('button', { name: 'Открыть' }))[0])
    await user.click(await screen.findByRole('button', { name: 'Настроить договор' }))
    expect((screen.getByLabelText('Цена договора') as HTMLInputElement).value).toBe('')
  })

  test('package form includes inspection and payment fields', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) return jsonResponse([objectRow])
      if (url.endsWith('/api/objects/1/treatments')) return jsonResponse([])
      if (url.endsWith('/api/objects/1/contract-timeline')) return jsonResponse([])
      if (url.endsWith('/api/transactions')) return jsonResponse([])
      return jsonResponse([])
    })
    const user = userEvent.setup()

    render(<ObjectsPage />)
    await user.click((await screen.findAllByRole('button', { name: 'Открыть' }))[0])
    await user.click(await screen.findByRole('button', { name: 'Пакет за месяц' }))

    expect(screen.getByLabelText('Месяц')).toBeTruthy()
    expect(screen.getByLabelText('Дата обследования')).toBeTruthy()
    expect(screen.getByLabelText('Контрольная дата')).toBeTruthy()
    expect(screen.getByLabelText('Препараты')).toBeTruthy()
    expect((screen.getByLabelText('Степень заражения') as HTMLInputElement).value).toBe(
      'начальная',
    )
    expect(screen.getByLabelText('Дополнительные услуги')).toBeTruthy()
    expect(screen.getByLabelText('Номер счёта')).toBeTruthy()
    expect(screen.getByLabelText('Привязать оплату')).toBeTruthy()
  })

  test('does not mix treatment history when cards are opened quickly', async () => {
    const secondObject = { ...objectRow, id: 2, name: 'Объект Б', contract: null }
    let resolveFirst: ((response: Response) => void) | undefined
    const firstHistory = new Promise<Response>((resolve) => {
      resolveFirst = resolve
    })
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/api/objects')) return jsonResponse([objectRow, secondObject])
      if (url.endsWith('/api/objects/1/treatments')) return firstHistory
      if (url.endsWith('/api/objects/2/treatments')) {
        return jsonResponse([
          {
            id: 2,
            object_id: 2,
            performed_at: '2026-08-21T10:00:00',
            performed_by: 'Алексей',
            notes: 'История объекта Б',
          },
        ])
      }
      return jsonResponse([])
    })
    const user = userEvent.setup()

    render(<ObjectsPage />)
    const openButtons = await screen.findAllByRole('button', { name: 'Открыть' })
    await user.click(openButtons[0])
    await user.click(openButtons[1])
    expect(await screen.findByText('История объекта Б')).toBeTruthy()

    resolveFirst?.(
      await jsonResponse([
        {
          id: 1,
          object_id: 1,
          performed_at: '2026-08-20T10:00:00',
          performed_by: 'Артём',
          notes: 'История объекта А',
        },
      ]),
    )
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.queryByText('История объекта А')).toBeNull()
    expect(screen.getByText('История объекта Б')).toBeTruthy()
  })
})
