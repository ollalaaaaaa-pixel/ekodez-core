import { useEffect, useState } from 'react'
import { Button, Card, Col, Modal, Row, Space, Statistic, Table, Tag, Typography, message } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'

const API = 'http://127.0.0.1:8000'

type Lead = {
  id: number
  source: string
  external_id: string | null
  order_at: string | null
  client_name: string | null
  phone: string | null
  address: string | null
  area: string | null
  reason: string | null
  comment: string | null
  amount_note: string | null
  contract: string | null
  partner: string | null
  status: string
}

const statusLabel: Record<string, { text: string; color: string }> = {
  new: { text: 'Новая', color: 'blue' },
  in_work: { text: 'В работе', color: 'orange' },
  done: { text: 'Выполнена', color: 'green' },
  cancelled: { text: 'Отмена', color: 'default' },
}

export default function LeadsPage() {
  const [rows, setRows] = useState<Lead[]>([])
  const [error, setError] = useState('')

  const load = () => {
    fetch(API + '/api/leads')
      .then((r) => r.json())
      .then(setRows)
      .catch(() => setError('Бэкенд недоступен. Запусти uvicorn.'))
  }

  useEffect(() => {
    load()
  }, [])

  const setStatus = (id: number, status: string) => {
    fetch(API + '/api/leads/' + id + '/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: status }),
    }).then(() => load())
  }

  const revealPii = (lead: Lead) => {
    Modal.confirm({
      title: 'Раскрыть персональные данные этой заявки?',
      content: 'Факт раскрытия будет записан в журнал безопасности.',
      okText: 'Да, показать',
      cancelText: 'Отмена',
      onOk: async () => {
        const response = await fetch(`${API}/api/leads/${lead.id}?show_pii=true`)
        if (!response.ok) {
          message.error('Не удалось раскрыть данные. Проверьте локальный доступ и ключ PII.')
          return
        }
        const revealed = (await response.json()) as Lead
        setRows((current) => current.map((row) => (row.id === lead.id ? revealed : row)))
      },
    })
  }

  const columns = [
    {
      title: 'Дата',
      dataIndex: 'order_at',
      key: 'date',
      render: (v: string | null) => (v ? v.slice(0, 16).replace('T', ' ') : ''),
    },
    { title: 'Клиент', dataIndex: 'client_name', key: 'name' },
    { title: 'Телефон', dataIndex: 'phone', key: 'phone' },
    { title: 'Адрес', dataIndex: 'address', key: 'address' },
    {
      title: 'Задача',
      key: 'job',
      render: (_: unknown, r: Lead) =>
        (r.reason ?? '') + (r.area ? ' / ' + r.area : ''),
    },
    { title: 'Сумма', dataIndex: 'amount_note', key: 'amount' },
    {
      title: 'Статус',
      key: 'status',
      render: (_: unknown, r: Lead) => {
        const m = statusLabel[r.status] ?? statusLabel.new
        return <Tag color={m.color}>{m.text}</Tag>
      },
    },
    {
      title: 'Действие',
      key: 'actions',
      render: (_: unknown, r: Lead) => (
        <Space>
          <Button size="small" onClick={() => revealPii(r)}>
            Показать полностью
          </Button>
          {r.status === 'new' ? (
            <>
              <Button size="small" type="primary" onClick={() => setStatus(r.id, 'in_work')}>
                В работу
              </Button>
              <Button size="small" danger onClick={() => setStatus(r.id, 'cancelled')}>
                Отмена
              </Button>
            </>
          ) : null}
          {r.status === 'in_work' ? (
            <>
              <Button size="small" type="primary" onClick={() => setStatus(r.id, 'done')}>
                Выполнена
              </Button>
              <Button size="small" danger onClick={() => setStatus(r.id, 'cancelled')}>
                Отмена
              </Button>
            </>
          ) : null}
        </Space>
      ),
    },
  ]

  const newCount = rows.filter((r) => r.status === 'new').length

  return (
    <div>
      <Row gutter={16}>
        <Col span={8}>
          <Card>
            <Statistic
              title="Новые заявки"
              value={newCount}
              prefix={<FileTextOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col span={16}>
          <Card>
            <Typography.Text type="secondary">
              Заявки из каналов и агрегаторов появляются здесь автоматически.
            </Typography.Text>
          </Card>
        </Col>
      </Row>
      {error ? <Typography.Paragraph type="warning">{error}</Typography.Paragraph> : null}
      <Card style={{ marginTop: 16 }} title="Заявки">
        <Table rowKey="id" columns={columns as any} dataSource={rows} pagination={{ pageSize: 10 }} />
      </Card>
    </div>
  )
}
