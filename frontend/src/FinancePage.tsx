import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Tag, Typography } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, EyeOutlined } from '@ant-design/icons'

const API = 'http://127.0.0.1:8000'

type Tx = {
  id: number
  source: string
  operation_date: string
  amount: string
  currency: string
  counterparty: string | null
  description: string | null
  kind: string
  review_required: boolean
}

type Summary = {
  income: string
  expense: string
  review_count: number
}

const kindLabel: Record<string, { text: string; color: string }> = {
  income: { text: 'Доход', color: 'green' },
  expense: { text: 'Расход', color: 'red' },
  own_transfer: { text: 'Перевод', color: 'blue' },
  unknown: { text: 'Неизвестно', color: 'default' },
}

export default function FinancePage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [rows, setRows] = useState<Tx[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(API + '/api/finance/summary')
      .then((r) => r.json())
      .then(setSummary)
      .catch(() => setError('Бэкенд недоступен. Запусти uvicorn.'))
    fetch(API + '/api/transactions')
      .then((r) => r.json())
      .then(setRows)
      .catch(() => setError('Бэкенд недоступен. Запусти uvicorn.'))
  }, [])

  const columns = [
    { title: 'Дата', dataIndex: 'operation_date', key: 'date' },
    { title: 'Контрагент', dataIndex: 'counterparty', key: 'cp' },
    { title: 'Назначение', dataIndex: 'description', key: 'desc' },
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
  ]

  return (
    <div>
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
      <Card style={{ marginTop: 16 }} title="Операции">
        <Table rowKey="id" columns={columns as any} dataSource={rows} pagination={{ pageSize: 10 }} />
      </Card>
    </div>
  )
}