import { useEffect, useState } from 'react'
import { Alert, Descriptions, Drawer, Input, Select, Space, Table, Tabs, Typography } from 'antd'
import { API } from './api'

type Client = { id: number; name: string; client_type: string; inn: string | null; legal_address: string | null; active_contracts: number }
type Row = { id: number; [key: string]: unknown }
type Card = Client & { requisites: Record<string, string | null>; objects: Row[]; contracts: Row[]; documents: Row[]; transactions: Row[]; inspections: Row[]; treatments: Row[] }
const labels: Record<string, string> = { phone: 'Телефон', representative: 'Представитель', representative_role: 'Должность', kpp: 'КПП', registration_number: 'ОГРН / ОГРНИП', bank_details: 'Банковские реквизиты' }
const columns = (fields: Record<string, string>) => Object.entries(fields).map(([key, title]) => ({ title, dataIndex: key, key, render: (value: unknown) => value == null ? '—' : String(value) }))

export default function ClientsPage() {
  const [rows, setRows] = useState<Client[]>([])
  const [query, setQuery] = useState('')
  const [type, setType] = useState<string | undefined>()
  const [selected, setSelected] = useState<number | null>(null)
  const [card, setCard] = useState<Card | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    const timer = setTimeout(() => {
      setLoading(true)
      const params = new URLSearchParams({ q: query })
      if (type) params.set('client_type', type)
      fetch(`${API}/api/clients?${params}`, { signal: controller.signal })
        .then(r => { if (!r.ok) throw new Error('Не удалось загрузить клиентов'); return r.json() })
        .then(data => { setRows(data); setError('') })
        .catch(e => { if (!controller.signal.aborted) setError(String(e)) })
        .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }, 200)
    return () => { clearTimeout(timer); controller.abort() }
  }, [query, type])
  useEffect(() => {
    if (selected === null) return
    const controller = new AbortController()
    fetch(`${API}/api/clients/${selected}`, { signal: controller.signal })
      .then(r => { if (!r.ok) throw new Error('Не удалось открыть карточку'); return r.json() })
      .then(setCard).catch(e => { if (!controller.signal.aborted) setError(String(e)) })
    return () => controller.abort()
  }, [selected])
  const tables = card ? [
    { key: 'objects', label: 'Объекты', children: <Table rowKey="id" dataSource={card.objects} columns={columns({ name: 'Название', address: 'Адрес', status: 'Статус' })} /> },
    { key: 'contracts', label: 'Договоры', children: <Table rowKey="id" dataSource={card.contracts} columns={columns({ number: 'Номер', start_date: 'Начало', end_date: 'Окончание', periodicity: 'Периодичность', price: 'Обработка, ₽', inspection_price: 'Осмотр, ₽' })} /> },
    { key: 'documents', label: 'Документы', children: <Table rowKey="id" dataSource={card.documents} columns={[...columns({ period_month: 'Месяц', invoice_number: 'Счёт', work_act_status: 'Статус акта' }), { title: 'Файлы', render: (_, row) => <Space orientation="vertical">{(row.file_manifest as { name: string; version: number }[]).map(file => <a key={`${file.version}-${file.name}`} href={`${API}/api/contract-periods/${row.id}/files/${encodeURIComponent(file.name)}`}>{file.name} · v{file.version}</a>)}</Space> }]} /> },
    { key: 'transactions', label: 'Операции', children: <Table rowKey="id" dataSource={card.transactions} columns={columns({ operation_date: 'Дата', amount: 'Сумма, ₽', kind: 'Тип', category: 'Категория' })} /> },
    { key: 'history', label: 'История', children: <><Typography.Title level={5}>Осмотры</Typography.Title><Table rowKey="id" dataSource={card.inspections} columns={columns({ inspection_date: 'Дата', contract_id: 'Договор', status: 'Статус' })} /><Typography.Title level={5}>Обработки</Typography.Title><Table rowKey="id" dataSource={card.treatments} columns={columns({ performed_at: 'Дата', object_id: 'Объект' })} /></> },
  ] : []
  return <>
    <Typography.Title level={3}>Клиенты</Typography.Title>
    {error && <Alert type="error" title={error} />}
    <Space wrap style={{ marginBottom: 16 }}>
      <Input.Search aria-label="Поиск клиентов" placeholder="Название или маскированный ИНН" value={query} onChange={e => setQuery(e.target.value)} allowClear />
      <Select aria-label="Тип клиента" placeholder="Юрлица и ИП" allowClear value={type} onChange={setType} style={{ width: 180 }} options={[{ value: 'legal_entity', label: 'Юрлица' }, { value: 'sole_proprietor', label: 'ИП' }]} />
    </Space>
    <Table rowKey="id" loading={loading} dataSource={rows} columns={[{ title: 'Название', render: (_, row) => <a onClick={() => { setCard(null); setSelected(row.id) }}>{row.name}</a> }, ...columns({ inn: 'ИНН', legal_address: 'Адрес', active_contracts: 'Активных договоров' })]} />
    <Drawer title={card?.name ?? 'Карточка клиента'} open={selected !== null} onClose={() => setSelected(null)} size="large" loading={!card}>
      {card && <Tabs items={[{ key: 'requisites', label: 'Реквизиты', children: <Descriptions column={1} items={[{ key: 'inn', label: 'ИНН', children: card.inn ?? '—' }, { key: 'address', label: 'Адрес', children: card.legal_address ?? '—' }, ...Object.entries(card.requisites).map(([key, value]) => ({ key, label: labels[key], children: value ?? '—' }))]} /> }, ...tables]} />}
    </Drawer>
  </>
}
