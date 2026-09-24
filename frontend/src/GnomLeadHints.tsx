import { useEffect, useState } from 'react'
import { Alert, Select, Space, Typography } from 'antd'
import { API } from './api'

type History = { last_treatment: string; pests: string[]; methods: string[]; price: string; warranty_until: string | null }
export default function GnomLeadHints({ address = '', phone = '', leadId }: { address?: string; phone?: string; leadId?: number }) {
  const [history, setHistory] = useState<History | null>(null)
  const [pest, setPest] = useState<string>()
  const [unit, setUnit] = useState<string>()
  const [city, setCity] = useState<string>()
  const [hint, setHint] = useState<{median_price:string|null;sample_count:number}|null>(null)
  useEffect(()=>{
    const controller = new AbortController()
    const timer = setTimeout(()=>{
      if (!leadId && !address.trim() && !phone.trim()) { setHistory(null); return }
      fetch(`${API}/api/gnom${leadId ? `/leads/${leadId}/history` : '/repeat'}`,{method:leadId ? 'GET' : 'POST',credentials:'include',headers:{'Content-Type':'application/json'},...(leadId ? {} : {body:JSON.stringify({address,phone})}),signal:controller.signal})
        .then(async r=>r.ok ? await r.json() : null).then(setHistory).catch(()=>undefined)
    },500)
    return ()=>{clearTimeout(timer);controller.abort()}
  },[address,phone,leadId])
  useEffect(()=>{
    const controller = new AbortController()
    if (!pest || !unit || !city) return
    fetch(`${API}/api/gnom/price-hint?${new URLSearchParams({pest,area_unit:unit,city})}`,{credentials:'include',signal:controller.signal})
      .then(async r=>r.ok ? await r.json() : null).then(setHint).catch(()=>undefined)
    return ()=>controller.abort()
  },[pest,unit,city])
  return <Space orientation="vertical" style={{width:'100%',marginBottom:16}}>
    {history ? <Alert type="info" title="Объект обслуживался" description={`Последняя обработка: ${history.last_treatment.slice(0,10)}; ${history.pests.join(', ')}; ${history.methods.join(', ')}; ${history.price} ₽. Гарантия: ${history.warranty_until || 'срок не настроен'}.`} /> : null}
    {!leadId ? <><Typography.Text strong>Справочная цена по истории</Typography.Text>
    <Select aria-label="Вредитель для справочной цены" placeholder="Вредитель" style={{width:'100%'}} value={pest} onChange={setPest} options={['клопы','тараканы','грызуны','плесень','клещи','муравьи'].map(value=>({value,label:value}))} />
    <Select aria-label="Тип площади" placeholder="Тип площади" style={{width:'100%'}} value={unit} onChange={setUnit} options={[{value:'rooms',label:'Комнаты'},{value:'m2',label:'м²'},{value:'sotki',label:'Сотки'}]} />
    <Select aria-label="Город для справочной цены" placeholder="Город" style={{width:'100%'}} value={city} onChange={setCity} options={['Архангельск','Северодвинск','Новодвинск'].map(value=>({value,label:value}))} />
    {hint ? <Typography.Text>По истории владельца: {hint.median_price ? `${hint.median_price} ₽, записей: ${hint.sample_count}` : 'нет подходящих записей'}. Цена заявки не меняется.</Typography.Text> : null}</> : null}
  </Space>
}
