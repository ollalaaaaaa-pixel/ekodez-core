import { describe, expect, it } from 'vitest'

import { apiBaseForHostname } from './api'

describe('apiBaseForHostname', () => {
  it('uses the browser hostname for the backend address', () => {
    expect(apiBaseForHostname('192.168.1.42')).toBe('http://192.168.1.42:8000')
  })

  it('keeps localhost working on the owner PC', () => {
    expect(apiBaseForHostname('localhost')).toBe('http://localhost:8000')
  })

  it('uses HTTPS for the backend when the UI is served over HTTPS', () => {
    expect(apiBaseForHostname('crm.example.test', 'https:')).toBe('https://crm.example.test:8000')
  })
})
