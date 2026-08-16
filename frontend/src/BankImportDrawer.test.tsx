import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import BankImportDrawer from './BankImportDrawer'

const reviewRow = (index: number) => ({
  operation_type: 'Дебет',
  operation_date: '2026-08-16',
  doc_number: String(index),
  amount: '1000.00',
  description: `Синтетическая операция ${index}`,
  payment_purpose: `Синтетический платёж ${index}`,
  counterparty_name: `Тестовый контрагент ${index}`,
  counterparty_inn: '',
  counterparty_inn_masked: '',
  source_hash: String(index).padStart(64, '0'),
  kind: 'expense',
  category: null,
  channel: null,
  comment: `Синтетический платёж ${index}`,
  needs_review: true,
  is_transfer: false,
  categoryOverride: 'Прочее',
})

const jsonResponse = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

describe('BankImportDrawer review confirmation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  test('unlocks after all three review rows and posts confirmation', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => jsonResponse([{ id: 1, name: 'Прочее' }]))
      .mockImplementationOnce(() =>
        jsonResponse([reviewRow(1), reviewRow(2), reviewRow(3)]),
      )
      .mockImplementationOnce(() =>
        jsonResponse({
          imported: 59,
          skipped_duplicates: 0,
          batch_id: 'synthetic-batch',
          imported_income_amount: '505300.80',
          imported_expense_amount: '109807.66',
          duplicate_income_amount: '0.00',
          duplicate_expense_amount: '0.00',
          excluded_credit_amount: '92262.00',
          excluded_debit_amount: '487755.00',
          statement_credit_total: '597562.80',
          statement_debit_total: '597562.66',
          credit_reconciled: true,
          debit_reconciled: true,
        }),
      )
    const onImported = vi.fn()
    const user = userEvent.setup()

    render(<BankImportDrawer open onClose={vi.fn()} onImported={onImported} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    const fileInput = document.querySelector('input[type="file"]')
    if (!(fileInput instanceof HTMLInputElement)) throw new Error('file input missing')
    await user.upload(
      fileInput,
      new File(['synthetic'], 'synthetic.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    )
    await user.click(screen.getByRole('button', { name: /Проверить выписку/ }))

    const submit = await screen.findByRole('button', {
      name: 'Подтвердить и сохранить',
    })
    expect(submit).toHaveProperty('disabled', true)
    expect(screen.queryByText('Спорные строки: 0 из 3 подтверждены')).not.toBeNull()

    for (let index = 0; index < 3; index += 1) {
      const confirmChoice = screen.getAllByRole('button', {
        name: 'Подтвердить выбор',
      })[0]
      expect(confirmChoice).toHaveProperty('disabled', false)
      await user.click(confirmChoice)
    }

    expect(screen.queryByText('Спорные строки: 3 из 3 подтверждены')).not.toBeNull()
    expect(submit).toHaveProperty('disabled', false)
    await user.click(submit)

    await waitFor(() => expect(onImported).toHaveBeenCalledOnce())
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[2][0]).toBe(
      'http://127.0.0.1:8000/api/bank/confirm',
    )
    const request = fetchMock.mock.calls[2][1]
    const payload = JSON.parse(String(request?.body)) as {
      transactions: Array<{ review_confirmed: boolean }>
    }
    expect(payload.transactions).toHaveLength(3)
    expect(payload.transactions.every((row) => row.review_confirmed)).toBe(true)
    expect(await screen.findByText('Импортировано 59 записей')).not.toBeNull()
  }, 20_000)
})
