import { afterEach, describe, expect, it, vi } from 'vitest'

import { authenticateTelegramMiniApp } from './auth'


afterEach(() => vi.restoreAllMocks())

describe('authenticateTelegramMiniApp', () => {
  it('requests a challenge before a credentialed Telegram login', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ challenge: 'synthetic-challenge' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ role: 'owner' }), { status: 200 }))

    await expect(authenticateTelegramMiniApp('signed-init-data')).resolves.toEqual({ role: 'owner' })
    expect(fetchMock).toHaveBeenNthCalledWith(1, expect.stringContaining('/api/auth/challenge'), {
      method: 'POST',
      credentials: 'include',
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, expect.stringContaining('/api/auth/telegram'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: 'signed-init-data', challenge: 'synthetic-challenge' }),
    })
  })

  it('surfaces the generic configured-role message from the backend', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ challenge: 'synthetic-challenge' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Не удалось войти. Настройте роль Telegram в конфиге.' }), { status: 403 }))

    await expect(authenticateTelegramMiniApp('signed-init-data')).rejects.toThrow(
      'Не удалось войти. Настройте роль Telegram в конфиге.',
    )
  })
})
