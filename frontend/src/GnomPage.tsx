import { useEffect, useState } from 'react'
import { Alert, Button, Card, Input, InputNumber, Modal, Select, Space, Switch, Table, Typography, message } from 'antd'
import { API } from './api'

type Run = { id: number; filename: string; sha256: string; rows: number; status: string; error: string | null }
type Candidate = { id: number; kind: string; preview: string; status: string; inventory_id: number | null }
type Expense = { id: number; amount: string; suggested_category: string; lead_id: number }
type Deal = { record_id: number; deal_id: string | null; platform: string | null; revenue: string; count: number }
type Overview = { settings: { weekly_enabled: boolean; warranty_days: number | null }; runs: Run[]; expenses: Expense[]; candidates: Candidate[]; analytics: { aggregators: Deal[]; revenue_by_month: Record<string,string>; average_check: string | null; lead_time_hours: string | null; rescheduled: number } }

async function api(path: string, method = 'GET', body?: unknown) {
  const response = await fetch(`${API}/api/gnom${path}`, { method, credentials: 'include', ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? 'Раздел доступен после входа владельца' : 'Операция не выполнена')
  return response.json()
}

export default function GnomPage() {
  const [data, setData] = useState<Overview>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState<File>()
  const [days, setDays] = useState<number | null>(null)
  const [categories, setCategories] = useState<Array<{id:number;title:string}>>([])
  const [inventory, setInventory] = useState<Array<{id:number;chemical_name:string}>>([])
  const [category, setCategory] = useState<number>()
  const [candidateInventory, setCandidateInventory] = useState<Record<number,number>>({})
  const [revealed, setRevealed] = useState<Record<number,string>>({})
  const [platform, setPlatform] = useState('')
  const [prefix, setPrefix] = useState('')
  const load = async () => { const result = await api('/overview') as Overview; setData(result); setDays(result.settings.warranty_days) }
  useEffect(() => {
    load().catch(reason => setError(String(reason)))
    fetch(`${API}/api/transaction-categories`, { credentials: 'include' }).then(r => r.json()).then(rows => setCategories(rows.filter((row: {kind:string;is_active:boolean}) => row.kind === 'expense' && row.is_active))).catch(() => undefined)
    fetch(`${API}/api/inventory`, { credentials: 'include' }).then(r => r.json()).then(setInventory).catch(() => undefined)
  }, [])
  const mutate = async (path: string, method: string, body: unknown) => { setBusy(true); try { await api(path, method, body); await load() } catch (reason) { message.error(String(reason)) } finally { setBusy(false) } }
  const importSelected = () => {
    if (!file) return
    Modal.confirm({ title: 'Импортировать выбранный файл истории?', content: 'Будут созданы или обновлены заявки, объекты и доходы. Расходы потребуют отдельного подтверждения.', okText: 'Импортировать', cancelText: 'Отмена', onOk: async () => {
      setBusy(true)
      try {
        const body = new FormData(); body.append('file', file)
        const response = await fetch(`${API}/api/gnom/import?confirmed=true`, { method: 'POST', credentials: 'include', body })
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'Импорт не выполнен')
        message.success(`Создано: ${result.created}, обновлено: ${result.updated}, без изменений: ${result.unchanged}`)
        await load()
      } catch (reason) { message.error(String(reason)); await load() } finally { setBusy(false) }
    } })
  }
  if (error) return <Alert type="warning" title={error} />
  if (!data) return <Typography.Text>Загрузка истории…</Typography.Text>
  return <Space orientation="vertical" size="large" style={{width:'100%'}}>
    <Card title="История CRM Гном">
      <Space wrap><input type="file" aria-label="Файл истории Гном" accept=".xlsx,.csv,.xls" onChange={event => setFile(event.target.files?.[0])} /><Button disabled={!file || busy} onClick={importSelected}>Импортировать файл</Button></Space>
      <Typography.Paragraph type="secondary">Имена, контакты и комментарии сохраняются зашифрованными. «Вы напарник» не используется. Имена файлов в журнале обезличены.</Typography.Paragraph>
      <Space wrap><Switch aria-label="Еженедельный импорт" checked={data.settings.weekly_enabled} disabled={busy} onChange={enabled => Modal.confirm({ title: enabled ? 'Разрешить импорт из папки каждый понедельник в 09:10?' : 'Остановить еженедельный импорт?', onOk: () => mutate('/settings', 'PATCH', { weekly_enabled: enabled, warranty_days: days }) })} /><span>Понедельник 09:10, папка import/gnom</span></Space>
      <Space wrap style={{marginTop:12}}><InputNumber aria-label="Срок гарантии в днях" placeholder="Гарантия, дней" min={0} max={3650} value={days} onChange={setDays} /><Button disabled={busy} onClick={() => mutate('/settings','PATCH',{...data.settings,warranty_days:days})}>Сохранить срок гарантии</Button></Space>
    </Card>
    <Card title="Журнал импорта"><Table rowKey="id" dataSource={data.runs} scroll={{x:650}} columns={[{title:'Файл',dataIndex:'filename'},{title:'Строк',dataIndex:'rows'},{title:'Статус',dataIndex:'status'},{title:'Ошибка',dataIndex:'error'}]} expandable={{expandedRowRender: row => <Typography.Text copyable>{row.sha256}</Typography.Text>}} /></Card>
    <Card title="Расходы на подтверждение">
      <Select aria-label="Категория расхода Гном" placeholder="Выберите расходную категорию" style={{width:'100%',maxWidth:360}} value={category} onChange={setCategory} options={categories.map(row => ({value:row.id,label:row.title}))} />
      <Table rowKey="id" dataSource={data.expenses} scroll={{x:500}} columns={[{title:'Заявка',render:(_,row) => `#${row.lead_id}`},{title:'Сумма',dataIndex:'amount'},{title:'Предположение',dataIndex:'suggested_category'},{title:'Действие',render:(_,row) => <Button disabled={!category || busy} onClick={() => mutate(`/records/${row.id}/expense`,'POST',{category_id:category})}>Подтвердить расход</Button>}]} />
    </Card>
    <Card title="Агрегаторы">
      <Space wrap><Input aria-label="Название платформы" placeholder="Название платформы" value={platform} onChange={e=>setPlatform(e.target.value)} /><Input aria-label="Префикс сделок" placeholder="Префикс номера (необязательно)" value={prefix} onChange={e=>setPrefix(e.target.value)} /></Space>
      <Table rowKey="record_id" dataSource={data.analytics.aggregators} scroll={{x:550}} columns={[{title:'Сделка',dataIndex:'deal_id'},{title:'Платформа',dataIndex:'platform'},{title:'Выручка',dataIndex:'revenue'},{title:'Заказов',dataIndex:'count'},{title:'Действие',render:(_,row)=><Button disabled={!platform || busy} onClick={()=>mutate(`/records/${row.record_id}/platform`,'PATCH',{platform,deal_prefix:prefix || null})}>Применить платформу</Button>}]} />
    </Card>
    <Card title="Кандидаты справочника и чек-листов">
      <Typography.Paragraph>Из истории, требует подтверждения. Подтверждение сохраняет решение владельца; состав препарата и расход заполняются в карточке склада.</Typography.Paragraph>
      {data.candidates.map(row=><Card key={row.id} size="small" style={{marginBottom:8}} title={`${row.kind} • ${row.status}`}>
        <Space orientation="vertical" style={{width:'100%'}}>
          <span>{revealed[row.id] || row.preview}</span>
          <Button onClick={()=>api(`/candidates/${row.id}/reveal`).then(result=>setRevealed(values=>({...values,[row.id]:result.value}))).catch(()=>message.error('Для раскрытия нужен вход владельца и локальный доступ или HTTPS'))}>Показать кандидата</Button>
          {row.kind === 'chemical' ? <Select aria-label={`Позиция склада для кандидата ${row.id}`} placeholder="Связать с позицией склада" style={{width:'100%'}} value={candidateInventory[row.id]} onChange={id=>setCandidateInventory(values=>({...values,[row.id]:id}))} options={inventory.map(item=>({value:item.id,label:item.chemical_name}))} /> : null}
          <Space><Button disabled={busy || !revealed[row.id]} onClick={()=>mutate(`/candidates/${row.id}`,'PATCH',{status:'confirmed',inventory_id:candidateInventory[row.id] || null})}>Подтвердить</Button><Button disabled={busy} onClick={()=>mutate(`/candidates/${row.id}`,'PATCH',{status:'rejected'})}>Отклонить</Button></Space>
        </Space>
      </Card>)}
    </Card>
    <Card title="Сезонность и сроки заявок">
      <Typography.Paragraph>Средний чек: {data.analytics.average_check || 'нет данных'} ₽. От создания до визита: {data.analytics.lead_time_hours || 'нет данных'} ч. Переносов: {data.analytics.rescheduled}.</Typography.Paragraph>
      <Table rowKey="month" dataSource={Object.entries(data.analytics.revenue_by_month).map(([month,revenue])=>({month,revenue}))} columns={[{title:'Месяц',dataIndex:'month'},{title:'Выручка',dataIndex:'revenue'}]} />
    </Card>
  </Space>
}
