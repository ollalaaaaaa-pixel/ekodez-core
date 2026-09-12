import { renderHook, waitFor, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useIncomeCategories } from './useIncomeCategories'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('uses server categories including an empty active list', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [{ title: 'Новый проект' }] })
  vi.stubGlobal('fetch', fetchMock)
  const first = renderHook(useIncomeCategories)
  await waitFor(() => expect(first.result.current).toEqual(['Новый проект']))
  first.unmount()
  fetchMock.mockResolvedValue({ ok: true, json: async () => [] })
  const second = renderHook(useIncomeCategories)
  await waitFor(() => expect(second.result.current).toEqual([]))
})
