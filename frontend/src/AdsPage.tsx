import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Select, Space, Table, Tabs, message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'

import { metricsUrl, metricValue } from './adsMetrics'

type Metric = { platform: string; campaign: string; spend: string; leads: number; revenue: string; cpl: string | null; romi: string | null }
type ImportRun = { id: number; platform: string; source_file: string; status: string; rows: number; created_at: string }
type QueueLead = { id: number; created_at: string; source: string; category: string | null }
type Notification = { id: number; kind: string; payload: Record<string, unknown>; created_at: string; read_at: string | null }

const api = '/api/ads'

export default function AdsPage({ onNotificationsRead }: { onNotificationsRead: () => void }) {
  const [platform, setPlatform] = useState('yandex_direct')
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [runs, setRuns] = useState<ImportRun[]>([])
  const [queue, setQueue] = useState<QueueLead[]>([])
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [error, setError] = useState('')
  const [range, setRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(30, 'day'),
    dayjs(),
  ])
  const load = useCallback(async () => {
    const [metricResponse, runsResponse, queueResponse, notificationResponse] = await Promise.all([
      fetch(metricsUrl(range[0], range[1]), { credentials: 'include' }),
      fetch(`${api}/import-runs`, { credentials: 'include' }),
      fetch(`${api}/attribution-queue`, { credentials: 'include' }),
      fetch(`${api}/notifications`, { credentials: 'include' }),
    ])
    if (![metricResponse, runsResponse, queueResponse, notificationResponse].every((item) => item.ok)) throw new Error('Не удалось загрузить рекламную аналитику')
    setMetrics(await metricResponse.json())
    setRuns(await runsResponse.json())
    setQueue(await queueResponse.json())
    setNotifications(await notificationResponse.json())
  }, [range])

  useEffect(() => { load().catch((reason: Error) => setError(reason.message)) }, [load])

  async function importFiles() {
    const response = await fetch(`${api}/import?platform=${encodeURIComponent(platform)}`, { method: 'POST', credentials: 'include' })
    if (!response.ok) return message.error('Импорт не выполнен')
    message.success('Импорт завершён')
    await load()
  }

  async function attribute(id: number, value: string) {
    await fetch(`${api}/leads/${id}/attribution`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ platform: value === 'none' ? null : value }) })
    await load()
  }

  async function readAll() {
    await Promise.all(notifications.filter((item) => !item.read_at).map((item) => fetch(`${api}/notifications/${item.id}/read`, { method: 'POST', credentials: 'include' })))
    onNotificationsRead()
    await load()
  }

  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    {error ? <Alert type="error" message={error} /> : null}
    <Card title="Импорт рекламы"><Space><Select value={platform} onChange={setPlatform} options={[{ value: 'yandex_direct', label: 'Яндекс Директ' }, { value: 'yandex_business', label: 'Яндекс Бизнес / Карты' }, { value: '2gis', label: '2ГИС' }]} /><Button type="primary" onClick={importFiles}>Импортировать</Button><DatePicker.RangePicker value={range} onChange={(value) => { if (value?.[0] && value[1]) setRange([value[0], value[1]]) }} /></Space></Card>
    <Tabs items={[
      { key: 'metrics', label: 'Метрики', children: <Table rowKey={(row) => `${row.platform}-${row.campaign}`} dataSource={metrics} pagination={false} columns={[{ title: 'Площадка', dataIndex: 'platform' }, { title: 'Кампания', dataIndex: 'campaign' }, { title: 'Расход', dataIndex: 'spend' }, { title: 'Лиды', dataIndex: 'leads' }, { title: 'CPL', dataIndex: 'cpl', render: metricValue }, { title: 'ROMI, %', dataIndex: 'romi', render: metricValue }]} /> },
      { key: 'queue', label: 'Очередь атрибуции', children: <Table rowKey="id" dataSource={queue} columns={[{ title: 'Заявка', dataIndex: 'id' }, { title: 'Источник', dataIndex: 'source' }, { title: 'Категория', dataIndex: 'category' }, { title: 'Решение', render: (_, row: QueueLead) => <Select aria-label={`Атрибуция заявки ${row.id}`} style={{ width: 210 }} placeholder="Выбрать площадку" onChange={(value) => attribute(row.id, value)} options={[{ value: 'yandex_direct', label: 'Яндекс Директ' }, { value: 'yandex_business', label: 'Яндекс Бизнес' }, { value: '2gis', label: '2ГИС' }, { value: 'none', label: 'Не реклама' }]} /> }]} /> },
      { key: 'runs', label: 'Журнал импортов', children: <Table rowKey="id" dataSource={runs} columns={[{ title: 'Площадка', dataIndex: 'platform' }, { title: 'Файл', dataIndex: 'source_file' }, { title: 'Статус', dataIndex: 'status' }, { title: 'Строк', dataIndex: 'rows' }]} /> },
      { key: 'notifications', label: 'Уведомления', children: <><Button onClick={readAll}>Отметить всё прочитанным</Button><Table rowKey="id" dataSource={notifications} columns={[{ title: 'Тип', dataIndex: 'kind' }, { title: 'Создано', dataIndex: 'created_at' }, { title: 'Прочитано', render: (_, row: Notification) => row.read_at ? 'Да' : 'Нет' }]} /></> },
    ]} />
  </Space>
}
