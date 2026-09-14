import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ClientsPage from './ClientsPage'

afterEach(() => vi.unstubAllGlobals())

it('loads masked clients and opens a card with related tabs', async () => {
  const client = { id: 1, name: 'ООО Тест', inn: '12***90', legal_address: '***', active_contracts: 1 }
  const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: () => Promise.resolve(url.includes('/clients/1') ? { ...client, requisites: {}, objects: [], contracts: [], documents: [], transactions: [], inspections: [], treatments: [] } : [client]) }))
  vi.stubGlobal('fetch', fetchMock)
  render(<ClientsPage />)
  fireEvent.click(await screen.findByText('ООО Тест'))
  await screen.findByRole('tab', { name: 'Реквизиты' })
  expect(screen.getByRole('tab', { name: 'Операции' })).toBeTruthy()
  fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск клиентов' }), { target: { value: 'Тест' } })
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('q=%D0%A2%D0%B5%D1%81%D1%82'), expect.anything()))
})
