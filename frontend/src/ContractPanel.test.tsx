import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import ContractPanel, { type ObjectSummary } from './ContractPanel'

const object: ObjectSummary = {
  id: 1, name: 'ТЕСТ объект', address: 'ТЕСТ адрес', type: 'hostel', area_sqm: '90.00',
  risk_points: [], status: 'active', last_treatment_date: null, next_treatment_date: null,
  contract: { id: 1, number: 'ТЕСТ-1', price: '3000.00', inspection_price: '3000.00',
    contract_date: '2026-08-01', periodicity: 'monthly', service_months: [],
    payment_term_business_days: 5, default_ksp: 5, default_derat_glue: 5, default_baits: 5,
    default_disinsection_glue: 6, start_date: null, end_date: null },
}
const saved = {
  revision: 'saved-revision',
  inspection: { id: 2, inspection_date: '2026-08-29', control_date: '2026-08-30',
    ksp_count: 9, derat_glue_count: 7, bait_count: 3, rodents_caught: 0,
    deratization_result: 'not_required', disinsection_glue_count: 8, insects_caught: 0,
    disinsection_result: 'not_required', status: 'draft', signed_at: null },
  period: { id: 3, invoice_number: 'ТЕСТ-3', invoice_date: '2026-08-31',
    paid_service_due: true, price_snapshot: '3000.00', preparations: 'ТЕСТ препарат',
    infestation_degree: 'Не обнаружено', extra_services: ['Услуга, с запятой', 'Вторая услуга'],
    work_act_status: 'draft', work_act_signed_at: null, transaction_id: null,
    generated_at: null as string | null,
    file_manifest: [] as { version: number; kind: string; name: string }[] },
}
const response = (data: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(data), { status }))
const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement

describe('Safe monthly package editing', () => {
  beforeEach(() => vi.restoreAllMocks())

  function setup(state = saved) {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => {
      if (String(url).includes('/package/')) {
        if (String(url).endsWith('/2027-01')) return response({ period: null, inspection: null, revision: 'new' })
        return response(options?.method === 'PATCH' ? { ...state, revision: 'updated' } : state)
      }
      return response([])
    })
    render(<ConfigProvider theme={{ token: { motion: false } }}><ContractPanel object={object} onObjectUpdated={vi.fn()} /></ConfigProvider>)
    return fetchMock
  }

  test('loads stored fields and submits no changed fields on unchanged save', async () => {
    const fetchMock = setup()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Пакет за месяц' }))
    await waitFor(() => expect(input('КСП').value).toBe('9'))
    expect(input('Дата обследования').value).toBe('2026-08-29')
    expect(input('Контрольная дата').value).toBe('2026-08-30')
    expect(input('Степень заражения').value).toBe('Не обнаружено')
    expect(input('Препараты').value).toBe('ТЕСТ препарат')
    expect(input('Дополнительные услуги').value).toBe('Услуга, с запятой\nВторая услуга')
    await user.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true))
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(String(call[1]?.body))).toEqual({ inspection: {}, period: {}, expected_revision: 'saved-revision', confirm_edit: false, generate: false })
  })

  test('requires confirmation before editing a signed version and submits only edited field', async () => {
    const state = structuredClone(saved)
    state.inspection.status = 'signed'
    Object.assign(state.inspection, { signed_at: '2026-08-31T12:00:00' })
    state.period.generated_at = '2026-08-31T12:00:00'
    state.period.file_manifest = [{ version: 5, kind: 'inspection', name: 'ТЕСТ.docx' }]
    const fetchMock = setup(state)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Пакет за месяц' }))
    expect(await screen.findByText('Подписано. Сформированы документы версии v5')).toBeTruthy()
    expect(input('Препараты').disabled).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Разрешить правку' }))
    await user.click(await screen.findByRole('button', { name: 'Отмена' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Подтверждаю правку' })).toBeNull())
    expect(input('Препараты').disabled).toBe(true)
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Разрешить правку' }))
    await user.click(await screen.findByRole('button', { name: 'Подтверждаю правку' }))
    await waitFor(() => expect(input('Препараты').disabled).toBe(false))
    fireEvent.change(input('Препараты'), { target: { value: 'ТЕСТ исправлено' } })
    await user.click(screen.getByRole('button', { name: 'Сохранить пакет' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true))
    const payload = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')![1]?.body))
    expect(payload.inspection).toEqual({})
    expect(payload.period).toEqual({ preparations: 'ТЕСТ исправлено' })
    expect(payload.confirm_edit).toBe(true)
  })

  test('new month loads defaults and clears previous document state', async () => {
    setup()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Пакет за месяц' }))
    await waitFor(() => expect(input('КСП').value).toBe('9'))
    fireEvent.change(input('Месяц'), { target: { value: '2027-01' } })
    await waitFor(() => expect(input('КСП').value).toBe('5'))
    expect(input('Степень заражения').value).toBe('начальная')
    expect(input('Препараты').value).toBe('')
    expect(input('Дополнительные услуги').value).toBe('')
  })

  test('failed load cannot save defaults over existing data', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(url => String(url).includes('/package/') ? response({}, 500) : response([]))
    render(<ContractPanel object={object} onObjectUpdated={vi.fn()} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Пакет за месяц' }))
    expect(await screen.findByText('Не удалось загрузить пакет. Повторите открытие формы.')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Сохранить черновик' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
