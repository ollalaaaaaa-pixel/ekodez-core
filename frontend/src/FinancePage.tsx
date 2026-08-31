import { useEffect, useState } from 'react'
import {
  Button, Card, Col, Empty, InputNumber, Modal, Progress, Row, Segmented, Select, Space,
  Spin, Statistic, Table, Tag, Typography, message,
} from 'antd'
import {
  ArrowDownOutlined, ArrowUpOutlined, EyeOutlined, UploadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import BankImportDrawer from './BankImportDrawer'
import './FinancePage.css'

const API = 'http://127.0.0.1:8000'

type Tx = {
  id: number
  source: string
  operation_date: string
  amount: string
  currency: string
  counterparty: string | null
  description: string | null
  category: string | null
  kind: string
  review_required: boolean
  object_id: number | null
  object_name: string | null
}

type ObjectOption = { id: number; name: string }

type Summary = {
  income: string
  expense: string
  review_count: number
}

type PeriodKey = 'week' | 'month' | 'quarter' | 'year'
type ChannelMetric = {
  channel: string
  total_amount: string
  count: number
  avg_check: string
  share_percent: string
}
type ChannelAnalytics = {
  period_total: string
  channels: ChannelMetric[]
}

const periodRange = (period: PeriodKey) => {
  const end = dayjs()
  if (period === 'week') return [end.subtract(6, 'day'), end] as const
  if (period === 'quarter') return [end.subtract(2, 'month').startOf('month'), end] as const
  if (period === 'year') return [end.startOf('year'), end] as const
  return [end.startOf('month'), end] as const
}

const money = (value: string | number) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(value))

const kindLabel: Record<string, { text: string; color: string }> = {
  income: { text: 'Доход', color: 'green' },
  expense: { text: 'Расход', color: 'red' },
  own_transfer: { text: 'Перевод', color: 'blue' },
  unknown: { text: 'Неизвестно', color: 'default' },
}

export default function FinancePage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [rows, setRows] = useState<Tx[]>([])
  const [draftAmounts, setDraftAmounts] = useState<Record<number, string | null>>({})
  const [period, setPeriod] = useState<PeriodKey>('month')
  const [channelAnalytics, setChannelAnalytics] = useState<ChannelAnalytics | null>(null)
  const [channelLoading, setChannelLoading] = useState(true)
  const [analyticsRefresh, setAnalyticsRefresh] = useState(0)
  const [bankImportOpen, setBankImportOpen] = useState(false)
  const [objects, setObjects] = useState<ObjectOption[]>([])
  const [linking, setLinking] = useState<Tx | null>(null)
  const [selectedObjectId, setSelectedObjectId] = useState<number | null>(null)
  const [linkSaving, setLinkSaving] = useState(false)
  const [error, setError] = useState('')

  const load = () => {
    fetch(API + '/api/finance/summary')
      .then((r) => r.json())
      .then(setSummary)
      .catch(() => setError('Бэкенд недоступен. Запусти uvicorn.'))
    fetch(API + '/api/transactions')
      .then((r) => r.json())
      .then(setRows)
      .catch(() => setError('Бэкенд недоступен. Запусти uvicorn.'))
    fetch(API + '/api/objects')
      .then((r) => r.json())
      .then(setObjects)
      .catch(() => setError('Не удалось загрузить объекты'))
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    const [start, end] = periodRange(period)
    const controller = new AbortController()
    setChannelLoading(true)
    fetch(
      `${API}/api/analytics/channels?start_date=${start.format('YYYY-MM-DD')}`
      + `&end_date=${end.format('YYYY-MM-DD')}`,
      { signal: controller.signal },
    )
      .then((response) => {
        if (!response.ok) throw new Error('Не удалось загрузить аналитику каналов')
        return response.json()
      })
      .then(setChannelAnalytics)
      .catch((fetchError: unknown) => {
        if (fetchError instanceof DOMException && fetchError.name === 'AbortError') return
        setError('Не удалось загрузить аналитику каналов')
      })
      .finally(() => {
        if (!controller.signal.aborted) setChannelLoading(false)
      })
    return () => controller.abort()
  }, [period, analyticsRefresh])

  const handleImported = () => {
    load()
    setAnalyticsRefresh((value) => value + 1)
  }

  const classify = (id: number, kind: string) => {
    const amount = draftAmounts[id]
    fetch(API + '/api/transactions/' + id + '/classify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kind: kind,
        review_required: false,
        ...(amount !== undefined && amount !== null ? { amount } : {}),
      }),
    }).then(() => load())
  }

  const saveObjectLink = async () => {
    if (!linking) return
    setLinkSaving(true)
    try {
      const response = await fetch(`${API}/api/transactions/${linking.id}/object`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ object_id: selectedObjectId }),
      })
      if (!response.ok) throw new Error('Не удалось привязать объект')
      setLinking(null)
      load()
      setAnalyticsRefresh((value) => value + 1)
      message.success(selectedObjectId === null ? 'Привязка снята' : 'Объект привязан')
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : 'Ошибка привязки')
    } finally {
      setLinkSaving(false)
    }
  }

  const columns = [
    { title: 'Дата', dataIndex: 'operation_date', key: 'date' },
    {
      title: 'Статья',
      dataIndex: 'category',
      key: 'category',
      render: (category: string | null) => category ?? 'Прочее',
    },
    {
      title: 'Детали',
      key: 'details',
      render: (_: unknown, r: Tx) => (
        <div>
          <div>{r.description ?? '—'}</div>
          {r.counterparty ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {r.counterparty}
            </Typography.Text>
          ) : null}
        </div>
      ),
    },
    {
      title: 'Тип',
      dataIndex: 'kind',
      key: 'kind',
      render: (k: string) => {
        const m = kindLabel[k] ?? kindLabel.unknown
        return <Tag color={m.color}>{m.text}</Tag>
      },
    },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      key: 'amount',
      render: (a: string, r: Tx) => {
        const n = Number(a)
        const sign = r.kind === 'expense' ? '-' : r.kind === 'income' ? '+' : ''
        return sign + n.toLocaleString('ru-RU') + ' ' + r.currency
      },
    },
    {
      title: 'Статус',
      key: 'status',
      render: (_: unknown, r: Tx) =>
        r.review_required ? (
          <Tag icon={<EyeOutlined />} color="orange">Требует проверки</Tag>
        ) : (
          <Tag color="green">Проведено</Tag>
        ),
    },
    {
      title: 'Объект',
      key: 'object',
      render: (_: unknown, r: Tx) => r.object_name ?? 'Не привязан',
    },
    {
      title: 'Действие',
      key: 'actions',
      render: (_: unknown, r: Tx) => (
        <Space wrap>
          {r.review_required ? (
            <>
            <InputNumber
              aria-label="Сумма операции"
              min="0"
              precision={2}
              stringMode
              value={draftAmounts[r.id] ?? r.amount}
              onChange={(value) =>
                setDraftAmounts((current) => ({
                  ...current,
                  [r.id]: value === null ? null : String(value),
                }))
              }
              style={{ width: 120 }}
            />
            <Button size="small" type="primary" onClick={() => classify(r.id, 'income')}>
              Доход
            </Button>
            <Button size="small" danger onClick={() => classify(r.id, 'expense')}>
              Расход
            </Button>
            </>
          ) : null}
          {r.kind === 'income' ? (
            <Button size="small" onClick={() => {
              setLinking(r)
              setSelectedObjectId(r.object_id)
            }}>
              {r.object_id === null ? 'Привязать объект' : 'Изменить объект'}
            </Button>
          ) : null}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="finance-toolbar">
        <Typography.Title level={3} style={{ margin: 0 }}>Финансы</Typography.Title>
        <Button
          type="primary"
          icon={<UploadOutlined />}
          onClick={() => setBankImportOpen(true)}
        >
          Импорт выписки (Т-Банк)
        </Button>
      </div>
      <Row gutter={16}>
        <Col span={8}>
          <Card>
            <Statistic
              title="Доход (подтверждённый)"
              value={Number(summary ? summary.income : 0)}
              precision={2}
              prefix={<ArrowUpOutlined />}
              valueStyle={{ color: '#3f8600' }}
              suffix="RUB"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Расход (подтверждённый)"
              value={Number(summary ? summary.expense : 0)}
              precision={2}
              prefix={<ArrowDownOutlined />}
              valueStyle={{ color: '#cf1322' }}
              suffix="RUB"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Требует проверки"
              value={summary ? summary.review_count : 0}
              prefix={<EyeOutlined />}
              valueStyle={{ color: '#d48806' }}
            />
          </Card>
        </Col>
      </Row>
      {error ? <Typography.Paragraph type="warning">{error}</Typography.Paragraph> : null}
      <Card
        className="channel-card"
        title="По каналам"
        extra={(
          <Segmented<PeriodKey>
            className="channel-periods"
            value={period}
            onChange={setPeriod}
            options={[
              { label: 'Неделя', value: 'week' },
              { label: 'Месяц', value: 'month' },
              { label: '3 месяца', value: 'quarter' },
              { label: 'Год', value: 'year' },
            ]}
          />
        )}
      >
        <Spin spinning={channelLoading}>
          <Typography.Paragraph type="secondary">
            Выручка за период: <strong>{money(channelAnalytics?.period_total ?? 0)} ₽</strong>
          </Typography.Paragraph>
          {!channelAnalytics?.channels.length ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Доходов за выбранный период нет" />
          ) : (
            <div className="channel-list">
              {channelAnalytics.channels.map((item) => (
                <div className="channel-item" key={item.channel}>
                  <div className="channel-heading">
                    <strong>{item.channel}</strong>
                    <span>{money(item.share_percent)}%</span>
                  </div>
                  <Progress percent={Number(item.share_percent)} showInfo={false} />
                  <div className="channel-metrics">
                    <strong>{money(item.total_amount)} ₽</strong>
                    <span>Заявок: {item.count}</span>
                    <span>Средний чек {money(item.avg_check)} ₽</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Spin>
      </Card>
      <Card style={{ marginTop: 16 }} title="Операции">
        <Table rowKey="id" columns={columns as any} dataSource={rows} pagination={{ pageSize: 10 }} />
      </Card>
      <BankImportDrawer
        open={bankImportOpen}
        onClose={() => setBankImportOpen(false)}
        onImported={handleImported}
      />
      <Modal
        title={linking?.object_id === null ? 'Привязать объект' : 'Изменить объект'}
        open={linking !== null}
        confirmLoading={linkSaving}
        okText="Сохранить привязку"
        cancelText="Отмена"
        onOk={() => void saveObjectLink()}
        onCancel={() => setLinking(null)}
      >
        <Select
          aria-label="Объект"
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="Выберите объект"
          value={selectedObjectId ?? undefined}
          onChange={(value) => setSelectedObjectId(value ?? null)}
          options={objects.map((item) => ({ value: item.id, label: item.name }))}
          style={{ width: '100%' }}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
          Сопоставление выполняется только вручную. Описание и контрагент не используются.
        </Typography.Paragraph>
      </Modal>
    </div>
  )
}
