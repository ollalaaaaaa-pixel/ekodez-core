import test from 'node:test'
import assert from 'node:assert/strict'
import { page, routes, escape } from '../src/site.mjs'
import { telegramLink, validateArea } from '../src/quiz.mjs'
import config from '../../config/telegram.json' with { type: 'json' }

test('every rendered Telegram link uses the configured bot', () => {
  const expected = '/' + config.BOT_USERNAME.replace(/^@/, '')
  assert.equal(new URL(telegramLink('?utm_source=vk')).pathname, expected)
  for (const route of routes) {
    for (const match of page(route).html.matchAll(/href="(https:\/\/t\.me\/[^" ]+)"/g)) {
      assert.equal(new URL(match[1]).pathname, expected)
    }
  }
})
test('all planned pages contain draft marker and consistent contacts',()=>{
  assert.equal(new Set(routes).size,routes.length)
  for(const route of routes){const p=page(route);assert.ok(p.title);assert.ok(p.html.includes('НЕ ОПУБЛИКОВАН'));assert.ok(p.html.includes('472-50-00'));assert.ok(!p.html.includes('undefined'))}
})
test('escape prevents HTML injection',()=>assert.equal(escape('<script>"&'),'&lt;script&gt;&quot;&amp;'))
test('positive area or explicit unknown required',()=>{
  for(const v of ['1','25,5','100.25','Не знаю']) assert.ok(validateArea(v),v)
  for(const v of ['','0','-1','NaN','Infinity','1e3','12<script>','999999999999']) assert.ok(!validateArea(v),v)
})
test('Telegram carries only allowlisted source, never contact or arbitrary UTM',()=>{
  assert.equal(telegramLink('?utm_source=vk&phone=secret'),'https://t.me/Ecodes29_Bot?start=quiz_vk')
  assert.equal(telegramLink('?utm_source=yandex'),'https://t.me/Ecodes29_Bot?start=quiz_yandex_direct')
  assert.equal(telegramLink('?utm_source=constructor'),'https://t.me/Ecodes29_Bot?start=quiz_site')
  assert.equal(telegramLink('?utm_source=%2B79210000000'),'https://t.me/Ecodes29_Bot?start=quiz_site')
})
