import { useEffect, useState } from 'react'
import {
  Button, Card, Col, Form, Input, InputNumber, Modal, Row, Select, Space,
  Segmented, Statistic, Table, Tag, Typography, message,
} from 'antd'
import { FileTextOutlined, PlusOutlined } from '@ant-design/icons'
import { API } from './api'
import { INCOME_CATEGORIES, LEAD_SOURCES, LEAD_SOURCE_LABELS } from './dictionaries'
import './LeadsPage.css'

type Lead = {
  id: number
  source: string
  category: string | null
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
  amount: string
  execution_date: string | null
  object_id: number | null
  performed_by: string
}

type ServiceObject = { id: number; name: string }

const useIsMobile = () => {
  const query = '(max-width: 767px)'
  const [mobile, setMobile] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setMobile(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return mobile
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
  const [intakeOpen, setIntakeOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [objects, setObjects] = useState<ServiceObject[]>([])
  const [editing, setEditing] = useState<Lead | null>(null)
  const [filter, setFilter] = useState<'all' | 'today'>('all')
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const isMobile = useIsMobile()

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
    const lead = rows.find((row) => row.id === id)
    if (status === 'done' && lead?.amount === '0.00') {
      message.info('Укажите сумму в заявке — автодоход не будет создан')
    }
    fetch(API + '/api/leads/' + id + '/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: status }),
    }).then(() => load())
  }

  const createLead = async (values: {
    source: string
    category: string
    clientName: string
    phone: string
    address: string
    amount?: number
    comment?: string
    executionDate?: string
  }) => {
    const lines = [
      `Имя клиента: ${values.clientName}`,
      `Телефон: ${values.phone}`,
      `Адрес: ${values.address}`,
      `Причина обращения: ${values.category}`,
    ]
    if (values.amount !== undefined && values.amount !== null) {
      lines.push(`Сумма: ${values.amount.toFixed(2)}`)
    }
    if (values.comment?.trim()) lines.push(`Комментарий: ${values.comment.trim()}`)

    setSaving(true)
    try {
      const response = await fetch(`${API}/api/leads/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: lines.join('\n'),
          source: values.source,
          category: values.category,
          amount: values.amount === undefined ? undefined : values.amount.toFixed(2),
          execution_date: values.executionDate || null,
        }),
      })
      if (!response.ok) throw new Error('lead ingest failed')
      const created = (await response.json()) as Lead
      setRows((current) => [created, ...current])
      form.resetFields()
      setIntakeOpen(false)
      message.success('Заявка сохранена')
    } catch {
      message.error('Не удалось сохранить заявку')
    } finally {
      setSaving(false)
    }
  }

  const openEdit = (lead: Lead) => {
    setEditing(lead)
    if (objects.length === 0) {
      fetch(API + '/api/objects')
        .then((response) => response.json())
        .then((data) => setObjects(Array.isArray(data) ? data : []))
        .catch(() => undefined)
    }
    editForm.setFieldsValue({
      amount: lead.amount,
      execution_date: lead.execution_date,
      category: lead.category,
      object_id: lead.object_id,
      performed_by: lead.performed_by,
    })
  }

  const saveEdit = async (values: {
    amount: string | number
    execution_date: string | null
    category: string | null
    object_id: number | null
    performed_by: string
  }) => {
    if (!editing) return
    setSaving(true)
    try {
      const response = await fetch(`${API}/api/leads/${editing.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: Number(values.amount).toFixed(2),
          execution_date: values.execution_date || null,
          category: values.category ?? null,
          object_id: values.object_id ?? null,
          performed_by: values.performed_by,
        }),
      })
      if (!response.ok) throw new Error('lead patch failed')
      const updated = (await response.json()) as Lead
      setRows((current) => current.map((row) => row.id === updated.id ? updated : row))
      setEditing(null)
      message.success('Заявка обновлена')
    } catch {
      message.error('Не удалось обновить заявку')
    } finally {
      setSaving(false)
    }
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
      title: 'Источник',
      dataIndex: 'source',
      key: 'source',
      render: (value: string) => LEAD_SOURCE_LABELS[value] ?? value,
    },
    { title: 'Услуга', dataIndex: 'category', key: 'category' },
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
          <Button size="small" onClick={() => openEdit(r)}>Редактировать</Button>
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
  const today = new Date().toLocaleDateString('en-CA')
  const visibleRows = filter === 'all' ? rows : rows.filter((row) =>
    row.execution_date !== null && row.execution_date <= today
    && (row.status === 'new' || row.status === 'in_work'))

  const mobileActions = (lead: Lead) => (
    <div className="lead-mobile-actions">
      <Button onClick={() => revealPii(lead)}>Показать полностью</Button>
      <Button onClick={() => openEdit(lead)}>Редактировать</Button>
      {lead.status === 'new' ? <Button type="primary" onClick={() => setStatus(lead.id, 'in_work')}>В работу</Button> : null}
      {lead.status === 'in_work' ? <Button type="primary" onClick={() => setStatus(lead.id, 'done')}>Выполнена</Button> : null}
    </div>
  )

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
      <Card
        style={{ marginTop: 16 }}
        title="Заявки"
        extra={(
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setIntakeOpen(true)}>
            Принять заявку
          </Button>
        )}
      >
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[{ label: 'Все', value: 'all' }, { label: 'Сегодня', value: 'today' }]}
          style={{ marginBottom: 16 }}
        />
        {isMobile ? (
          <div className="lead-mobile-list">
            {visibleRows.map((lead) => {
              const status = statusLabel[lead.status] ?? statusLabel.new
              return (
                <Card key={lead.id} data-testid="lead-mobile-card" size="small" title={`Заявка #${lead.id}`} extra={<Tag color={status.color}>{status.text}</Tag>}>
                  <div className="lead-mobile-details">
                    <strong>{lead.client_name || 'Клиент'}</strong>
                    <span>{lead.phone || 'Телефон не указан'}</span>
                    <span>{lead.address || 'Адрес не указан'}</span>
                    <span>Дата: {lead.execution_date || 'не назначена'}</span>
                    <span>Услуга: {lead.category || 'не указана'}</span>
                    <span>Сумма: {lead.amount} ₽</span>
                  </div>
                  {mobileActions(lead)}
                </Card>
              )
            })}
          </div>
        ) : (
          <div data-testid="lead-desktop-table">
            <Table rowKey="id" columns={columns as any} dataSource={visibleRows} pagination={{ pageSize: 10 }} />
          </div>
        )}
      </Card>
      <Modal
        title="Новая заявка"
        open={intakeOpen}
        onCancel={() => setIntakeOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ source: 'other' }}
          onFinish={createLead}
        >
          <Form.Item name="source" label="Источник" rules={[{ required: true }]}>
            <Select options={[...LEAD_SOURCES]} />
          </Form.Item>
          <Form.Item name="category" label="Услуга" rules={[{ required: true }]}>
            <Select options={INCOME_CATEGORIES.map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item name="clientName" label="Имя клиента" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="phone" label="Телефон" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="address" label="Адрес" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="amount" label="Сумма (необязательно)">
            <InputNumber min={0} precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="executionDate" label="Дата обработки">
            <Input type="date" />
          </Form.Item>
          <Form.Item name="comment" label="Комментарий">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block>
            Сохранить заявку
          </Button>
        </Form>
      </Modal>
      <Modal
        title="Редактировать заявку"
        open={editing !== null}
        onCancel={() => setEditing(null)}
        footer={null}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" onFinish={saveEdit}>
          <Form.Item name="amount" label="Сумма" rules={[{ required: true }]}>
            <InputNumber stringMode min="0" precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="execution_date" label="Дата обработки">
            <Input type="date" />
          </Form.Item>
          <Form.Item name="category" label="Услуга">
            <Select allowClear options={INCOME_CATEGORIES.map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item name="object_id" label="Объект">
            <Select allowClear options={objects.map((row) => ({ value: row.id, label: row.name }))} />
          </Form.Item>
          <Form.Item name="performed_by" label="Исполнитель" rules={[{ required: true }]}>
            <Select options={['Артём', 'Алексей'].map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block>
            Сохранить изменения
          </Button>
        </Form>
      </Modal>
    </div>
  )
}
