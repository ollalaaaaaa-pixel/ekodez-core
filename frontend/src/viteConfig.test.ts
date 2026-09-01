import { describe, expect, it } from 'vitest'

import config from '../vite.config'

describe('Vite LAN configuration', () => {
  it('listens on all interfaces', () => {
    expect(config.server?.host).toBe(true)
  })
})
