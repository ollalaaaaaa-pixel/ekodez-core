import { describe, expect, it } from 'vitest'

import { apiBaseForHostname } from './api'

describe('apiBaseForHostname', () => {
  it('uses the browser hostname for the backend address', () => {
    expect(apiBaseForHostname('192.168.1.42')).toBe('http://192.168.1.42:8000')
  })

  it('keeps localhost working on the owner PC', () => {
    expect(apiBaseForHostname('localhost')).toBe('http://localhost:8000')
  })
})
