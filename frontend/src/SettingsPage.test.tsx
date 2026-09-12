import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('saves drag order and edits a category through API', async () => {
  const rows = [{ id: 1, title: 'Один', kind: 'expense', sort_order: 0 }, { id: 2, title: 'Два', kind: 'expense', sort_order: 1 }]
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => rows })
  vi.stubGlobal('fetch', fetchMock)
  render(<SettingsPage />)
  const first = (await screen.findByText('Один')).parentElement!
  const second = screen.getByText('Два').parentElement!
  fireEvent.dragStart(first)
  fireEvent.dragOver(second)
  fireEvent.drop(second)
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/reorder'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ items: [{ id: 2, sort_order: 0 }, { id: 1, sort_order: 1 }] }) })))
  await waitFor(() => expect(screen.getAllByText('Изменить')[0].closest('button')!.disabled).toBe(false))
  fireEvent.click(screen.getAllByText('Изменить')[0])
  fireEvent.change(screen.getByLabelText('Название категории'), { target: { value: 'Новое' } })
  fireEvent.click(screen.getByText('Сохранить'))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/transaction-categories/1'), expect.objectContaining({ method: 'PATCH', body: expect.stringContaining('Новое') })))
})
