import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import { ChemicalDetails, ChemicalRecommendations, pestForCategory } from './ChemicalDictionary'

describe('Chemical dictionary', () => {
  test('shows every saved field and alternative name', () => {
    render(<ChemicalDetails row={{ active_substance: 'ТЕСТ вещество', resistance_note: 'Заметка владельца', dosage_note: 'По инструкции', hazard_class: 'ТЕСТ класс', pest_tags: ['клопы'], alternatives: [2] }} positions={[{ id: 2, chemical_name: 'Альтернатива', quantity: '1.000', unit: 'л' }]} />)
    for (const value of ['ТЕСТ вещество', 'Заметка владельца', 'По инструкции', 'ТЕСТ класс', 'клопы', 'Альтернатива']) expect(screen.getByText(value)).toBeTruthy()
  })

  test('maps only unambiguous categories', () => {
    expect(pestForCategory('Дератизация')).toBe('грызуны')
    expect(pestForCategory('Обработка от клещей')).toBe('клещи')
    expect(pestForCategory('Дезинсекция')).toBeUndefined()
  })

  test('fetches recommendations and asks for pest for a generic category', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([{ id: 1, chemical_name: 'ТЕСТ препарат', quantity: '2.000', unit: 'л', dosage_note: 'По инструкции' }])))
    const user = userEvent.setup()
    render(<ChemicalRecommendations category="Дезинсекция" />)
    expect(fetchMock).not.toHaveBeenCalled()
    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByTitle('клопы'))
    expect(await screen.findByText('ТЕСТ препарат — 2.000 л')).toBeTruthy()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('pest='), expect.objectContaining({ credentials: 'include' })))
    expect(decodeURIComponent(String(fetchMock.mock.calls[0][0]))).toContain('клопы')
    fetchMock.mockRestore()
  })
})
