import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { motion } from 'framer-motion'
import { page } from './site.mjs'
import { telegramLink, validateArea } from './quiz.mjs'
import './style.css'

const root = document.getElementById('root')!
if (!root.children.length) {
  const current = page(location.pathname.replace(/\/$/, '') || '/')
  root.innerHTML = current.html
  document.title = current.title
}
const campaignSource = new URLSearchParams(location.search).get('utm_source')
if (campaignSource && ['vk', 'avito', 'yandex', 'yandex_direct', 'seo'].includes(campaignSource)) {
  document.querySelectorAll<HTMLAnchorElement>('a[href]').forEach(link => {
    const url = new URL(link.href)
    if (url.origin === location.origin) {
      url.searchParams.set('utm_source', campaignSource)
      link.href = url.pathname + url.search + url.hash
    }
  })
}

function Quiz() {
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState(['', '', '', '', ''])
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const questions = ['Что нужно решить?', 'Какой объект?', 'Примерная площадь', 'Когда удобно обсудить?', 'Как продолжим?']
  const choices: Record<number, string[]> = {
    0: ['Тараканы', 'Клопы', 'Грызуны', 'Клещи', 'Плесень', 'Обслуживание бизнеса', 'Другое'],
    1: ['Квартира', 'Частный дом', 'Участок', 'Объект бизнеса'],
    3: ['Как можно скорее', 'На этой неделе', 'Пока сравниваю варианты'],
    4: ['Напишу в Telegram', 'Позвоню сам'],
  }
  function update(value: string) {setAnswers(answers.map((a,i) => i === step ? value : a)); setError('')}
  function next() {
    if (!answers[step] || (step === 2 && !validateArea(answers[step]))) {setError(step === 2 ? 'Введите площадь больше нуля или выберите «Не знаю».' : 'Выберите ответ.'); return}
    setStep(step + 1)
  }
  const summary = `Здравствуйте! Хочу обсудить задачу.\nПроблема: ${answers[0]}.\nОбъект: ${answers[1]}.\nПлощадь: ${answers[2]}${answers[2] === 'Не знаю' ? '' : answers[1] === 'Участок' ? ' соток' : ' м²'}.\nСрок: ${answers[3]}.\nПрошу уточнить подготовку, стоимость и условия контроля.`
  return <div className="quiz"><p className="eyebrow">ШАГ {Math.min(step + 1,5)} ИЗ 5</p><div className="progress" role="progressbar" aria-label="Прогресс" aria-valuemin={0} aria-valuemax={5} aria-valuenow={Math.min(step+1,5)}><span style={{width:`${Math.min(step+1,5)*20}%`}} /></div>
    {step < 5 ? <motion.div key={step} initial={{opacity:0,y:8}} animate={{opacity:1,y:0}}><h2>{questions[step]}</h2>
      {step === 2 ? <><label htmlFor="area">{answers[1] === 'Участок' ? 'Сотки' : 'Квадратные метры'}</label><input id="area" inputMode="decimal" value={answers[2] === 'Не знаю' ? '' : answers[2]} onChange={e=>update(e.target.value)} /><button className="option" aria-pressed={answers[2]==='Не знаю'} onClick={()=>update('Не знаю')}>Не знаю</button></> : <div className="options">{choices[step].map(c=><button key={c} className="option" aria-pressed={answers[step]===c} onClick={()=>update(c)}>{c}</button>)}</div>}
      {step === 4 && <p className="muted">Контактные данные здесь не собираются. Ответы не отправляются автоматически; следующий шаг — самостоятельный разговор.</p>}
      <p role="alert">{error}</p><div className="actions">{step>0 && <button onClick={()=>{setStep(step-1);setError('')}}>Назад</button>}<button className="button" onClick={next}>Далее →</button></div>
    </motion.div> : <div><h2>Сначала обсудим условия</h2><p>Заявка ещё не отправлена. Итоговую стоимость и возможность выезда подтвердит специалист.</p><pre>{summary}</pre><div className="actions"><button onClick={async()=>{try {await navigator.clipboard.writeText(summary);setCopied(true)} catch {setError('Не удалось скопировать. Выделите текст выше вручную.')}}}>{copied?'Скопировано':'Скопировать ответы'}</button>{answers[4]==='Позвоню сам' ? <a className="button" href="tel:+79214725000">Позвонить</a> : <a className="button" href={telegramLink(location.search)} rel="noreferrer">Открыть Telegram</a>}</div><p role="alert">{error}</p><p className="muted">В Telegram нажмите «Старт» и отправьте скопированный текст. В ссылку не включаются ответы, телефон или имя. Передача атрибуции в Core требует отдельной проверки B6.</p></div>}
    <details><summary>«Дорого» или «уже обрабатывали — не помогло»?</summary><p>Сравним состав работ, подготовку и контроль, а не только первую цифру. При повторном появлении нужны даты и места наблюдений; две недели сами по себе не доказывают причину. В сложных случаях — уменьшение численности без гарантии по времени. Условия повторного обращения согласуем до работ.</p></details>
  </div>
}
const quiz = document.getElementById('quiz')
if (quiz) createRoot(quiz).render(<React.StrictMode><Quiz /></React.StrictMode>)
