import { API } from './api'

export type AuthSession = { role: 'owner' | 'master' }
export type AuthSessionStatus = {
  authenticated: boolean
  role: AuthSession['role'] | null
}

declare global {
  interface Window {
    Telegram?: { WebApp?: { initData?: string; ready?: () => void } }
  }
}

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: string }
    return body.detail || 'Не удалось войти через Telegram'
  } catch {
    return 'Не удалось войти через Telegram'
  }
}

export async function authenticateTelegramMiniApp(initData: string): Promise<AuthSession> {
  const challengeResponse = await fetch(`${API}/api/auth/challenge`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!challengeResponse.ok) throw new Error(await responseDetail(challengeResponse))
  const { challenge } = await challengeResponse.json() as { challenge: string }
  const loginResponse = await fetch(`${API}/api/auth/telegram`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: initData, challenge }),
  })
  if (!loginResponse.ok) throw new Error(await responseDetail(loginResponse))
  return await loginResponse.json() as AuthSession
}

export function telegramMiniAppInitData(): string {
  return window.Telegram?.WebApp?.initData?.trim() || ''
}

export async function getAuthSession(): Promise<AuthSessionStatus> {
  const response = await fetch(`${API}/api/auth/session`, { credentials: 'include' })
  if (!response.ok) return { authenticated: false, role: null }
  return await response.json() as AuthSessionStatus
}
