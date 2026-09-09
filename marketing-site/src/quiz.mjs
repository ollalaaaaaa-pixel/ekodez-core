export function validateArea(value) {
  return value === 'Не знаю' || (/^\d+(?:[.,]\d{1,2})?$/.test(value.trim()) && Number(value.replace(',', '.')) > 0 && Number(value.replace(',', '.')) <= 10000000)
}
export function telegramLink(search) {
  const source = new URLSearchParams(search).get('utm_source')
  const allowed = {vk:'vk', avito:'avito', yandex:'yandex_direct', yandex_direct:'yandex_direct', seo:'seo'}
  const tag = Object.hasOwn(allowed, source ?? '') ? allowed[source] : 'site'
  return `https://t.me/ekodez_bot?start=m_${tag}`
}
