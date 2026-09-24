import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return {
    ...actual,
    telegramMiniAppInitData: () => 'signed-init-data',
    authenticateTelegramMiniApp: vi.fn(),
  }
})

import { authenticateTelegramMiniApp } from './auth'

afterEach(() => vi.restoreAllMocks())

describe('owner-only advertising navigation', () => {
  it('shows advertising and its notification bell only to owner', async () => {
    vi.mocked(authenticateTelegramMiniApp).mockResolvedValue({ role: 'owner' })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ count: 2 }), { status: 200 }),
    )
    render(<App />)
    expect(await screen.findByText('Реклама')).toBeTruthy()
    await waitFor(() =>
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/ads/notifications/unread-count',
        { credentials: 'include' },
      ),
    )
    expect(screen.getByRole('button', { name: 'Уведомления рекламы' })).toBeTruthy()
  })

  it('hides advertising and its notification bell from master', async () => {
    vi.mocked(authenticateTelegramMiniApp).mockResolvedValue({ role: 'master' })
    render(<App />)
    await waitFor(() => expect(screen.queryByText('Вход через Telegram…')).toBeNull())
    expect(screen.queryByText('Реклама')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Уведомления рекламы' })).toBeNull()
  })
})
