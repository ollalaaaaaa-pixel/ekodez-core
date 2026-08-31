import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import InventoryPage from './InventoryPage'

const inventoryRow = {
  id: 1,
  chemical_name: 'Циперметрин',
  quantity: '9.000',
  initial_quantity: '100.000',
  unit: 'мл',
  batch_number: 'B-001',
  expiry_date: '2027-08-01',
  supplier: 'Поставщик',
  low_stock: true,
}

const objectRow = {
  id: 1,
  name: 'СК Ворон',
  address: 'П. Галушина 21 к.1',
  type: 'gym',
  area_sqm: '200.00',
  contract: null,
  risk_points: [],
  last_treatment_date: null,
  next_treatment_date: null,
  status: 'active',
}

const treatmentRow = {
  id: 10,
  lead_id: null,
  object_id: 1,
  chemicals_used: [
    {
      id: 20,
      inventory_id: 1,
      chemical_name: 'Циперметрин',
      quantity_used: '1.250',
      unit: 'мл',
    },
  ],
  performed_at: '2026-08-26T12:30:00',
  performed_by: 'Артём',
  notes: 'Профилактика',
}

const jsonResponse = (body: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

describe('Inventory screen', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })))
  })

  test('shows stock, low-stock alert and treatment history', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/api/inventory')) return jsonResponse([inventoryRow])
      if (url.endsWith('/api/treatments')) return jsonResponse([treatmentRow])
      if (url.endsWith('/api/objects')) return jsonResponse([objectRow])
      return jsonResponse([])
    })

    render(<InventoryPage />)

    expect(await screen.findByText('Циперметрин')).toBeTruthy()
    expect(screen.getByText('9.000 мл')).toBeTruthy()
    expect(screen.getByText('Низкий остаток')).toBeTruthy()
    expect(screen.getByText('Профилактика')).toBeTruthy()
    expect(screen.getByText('1.250 мл')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Добавить препарат/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Списать на обработку/ })).toBeTruthy()
  })

  test('creates inventory using decimal strings', async () => {
    let listCalls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith('/api/inventory') && init?.method === 'POST') {
        return jsonResponse({ ...inventoryRow, quantity: '100.000', low_stock: false })
      }
      if (url.endsWith('/api/inventory')) {
        listCalls += 1
        return jsonResponse(listCalls === 1 ? [] : [{ ...inventoryRow, quantity: '100.000', low_stock: false }])
      }
      if (url.endsWith('/api/treatments') || url.endsWith('/api/objects')) {
        return jsonResponse([])
      }
      return jsonResponse([])
    })
    const user = userEvent.setup()

    render(<InventoryPage />)
    await user.click(await screen.findByRole('button', { name: /Добавить препарат/ }))
    await user.type(screen.getByPlaceholderText('Название препарата'), 'Циперметрин')
    await user.type(screen.getByPlaceholderText('Количество'), '100')
    await user.type(screen.getByPlaceholderText('Единица'), 'мл')
    await user.type(screen.getByPlaceholderText('Номер партии'), 'B-001')
    await user.type(screen.getByPlaceholderText('Срок годности'), '2027-08-01')
    await user.type(screen.getByPlaceholderText('Поставщик'), 'Поставщик')
    await user.click(screen.getByRole('button', { name: 'Сохранить' }))

    expect(await screen.findByText('100.000 мл')).toBeTruthy()
    const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      chemical_name: 'Циперметрин',
      quantity: '100.000',
      unit: 'мл',
      batch_number: 'B-001',
    })
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  }, 15_000)

  test('renders stock and treatments as cards at 390px without tables', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: query.includes('767px'), media: query,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })))
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/api/inventory')) return jsonResponse([inventoryRow])
      if (url.endsWith('/api/treatments')) return jsonResponse([treatmentRow])
      if (url.endsWith('/api/objects')) return jsonResponse([objectRow])
      return jsonResponse([])
    })
    render(<div style={{ width: 390 }}><InventoryPage /></div>)

    expect(await screen.findAllByTestId('inventory-mobile-card')).toHaveLength(1)
    expect(screen.getAllByTestId('treatment-mobile-card')).toHaveLength(1)
    expect(screen.queryByTestId('inventory-desktop-table')).toBeNull()
    expect(screen.getByText('9.000 мл')).toBeTruthy()
    expect(screen.getByText('1.250 мл')).toBeTruthy()
  }, 15_000)
})
