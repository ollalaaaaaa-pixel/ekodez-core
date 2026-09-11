import config from '../../config/telegram.json' with { type: 'json' }

export const BOT_USERNAME = config.BOT_USERNAME
export const BOT_URL = `https://t.me/${BOT_USERNAME.replace(/^@/, '')}`
