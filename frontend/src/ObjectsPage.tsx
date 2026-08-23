import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

const API = 'http://127.0.0.1:8000'

type Contract = {
  id: number
  number: string
  monthly_amount: string
  start_date: string | null
  end_date: string | null
}

type ServiceObject = {
  id: number
  name: string
  address: string
  type: string
  area_sqm: string
  contract: Contract | null
  risk_points: string[]
  last_treatment_date: string | null
  next_treatment_date: string | null
  status: string
}

type Treatment = {
  id: number
  performed_at: string
  performed_by: string
  notes: string | null
}

type ObjectForm = {
  name: string
  address: string
  type: string
  area_sqm: string
  contract_number?: string
  monthly_amount?: string
  risk_points?: string
}

const typeOptions = [
  { value: 'restaurant', label: 'Ресторан' },
  { value: 'gym', label: 'Спортзал' },
  { value: 'kindergarten', label: 'Детский сад' },
  { value: 'apartment', label: 'Квартира' },
  { value: 'office', label: 'Офис' },
  { value: 'other', label: 'Другое' },
]

const statusOptions = [
  { value: 'active', label: 'Активный' },
  { value: 'warranty', label: 'Гарантия' },
  { value: 'overdue', label: 'Просрочен' },
  { value: 'inactive', label: 'Неактивный' },
]

const statusMeta: Record<string, { text: string; color: string }> = {
  active: { text: 'Активный', color: 'green' },
  warranty: { text: 'Гарантия', color: 'gold' },
  overdue: { text: 'Просрочен', color: 'red' },
  inactive: { text: 'Неактивный', color: 'default' },
}

const typeLabel = (value: string) =>
  typeOptions.find((option) => option.value === value)?.label ?? value

const moneyLabel = (value: string) => {
  const [whole, fraction = ''] = value.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return `${grouped}.${fraction.padEnd(2, '0').slice(0, 2)} ₽/мес`
}

const decimalString = (value: string | undefined) => {
  const normalized = (value ?? '0').trim().replace(',', '.')
  const [whole = '0', fraction = ''] = normalized.split('.')
  return `${whole}.${fraction.padEnd(2, '0').slice(0, 2)}`
}

const dateLabel = (value: string | null) => {
  if (!value) return '—'
  const [year, month, day] = value.split('-')
  return `${day}.${month}.${year}`
}

export default function ObjectsPage() {
  const [rows, setRows] = useState<ServiceObject[]>([])
  const [typeFilter, setTypeFilter] = useState<string>()
  const [statusFilter, setStatusFilter] = useState<string>()
  const [createOpen, setCreateOpen] = useState(false)
  const [selected, setSelected] = useState<ServiceObject | null>(null)
  const [treatments, setTreatments] = useState<Treatment[]>([])
  const listRequest = useRef(0)
  const historyRequest = useRef(0)
  const [form] = Form.useForm<ObjectForm>()

  const load = useCallback(() => {
    const requestId = ++listRequest.current
    const query = new URLSearchParams()
    if (typeFilter) query.set('type', typeFilter)
    if (statusFilter) query.set('status', statusFilter)
    const suffix = query.size ? `?${query.toString()}` : ''
    fetch(`${API}/api/objects${suffix}`)
      .then((response) => response.json())
      .then((data: ServiceObject[]) => {
        if (listRequest.current === requestId) setRows(data)
      })
      .catch(() => {
        if (listRequest.current === requestId) message.error('Не удалось загрузить объекты')
      })
  }, [typeFilter, statusFilter])

  useEffect(() => {
    load()
  }, [load])

  const createObject = async (values: ObjectForm) => {
    const response = await fetch(`${API}/api/objects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: values.name,
        address: values.address,
        type: values.type,
        area_sqm: decimalString(values.area_sqm),
        contract: values.contract_number
          ? {
              number: values.contract_number,
              monthly_amount: decimalString(values.monthly_amount),
            }
          : null,
        risk_points: (values.risk_points ?? '')
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
        status: 'active',
      }),
    })
    if (!response.ok) {
      message.error('Не удалось сохранить объект')
      return
    }
    setCreateOpen(false)
    form.resetFields()
    load()
  }

  const openCard = async (row: ServiceObject) => {
    const requestId = ++historyRequest.current
    setSelected(row)
    setTreatments([])
    const response = await fetch(`${API}/api/objects/${row.id}/treatments`)
    const history = response.ok ? ((await response.json()) as Treatment[]) : []
    if (historyRequest.current === requestId) setTreatments(history)
  }

  const closeCard = () => {
    historyRequest.current += 1
    setTreatments([])
    setSelected(null)
  }

  const columns = [
    { title: 'Объект', dataIndex: 'name', key: 'name' },
    { title: 'Адрес', dataIndex: 'address', key: 'address' },
    {
      title: 'Тип',
      dataIndex: 'type',
      key: 'type',
      render: (value: string) => typeLabel(value),
    },
    {
      title: 'Площадь',
      dataIndex: 'area_sqm',
      key: 'area',
      render: (value: string) => `${value} м²`,
    },
    {
      title: 'Статус',
      dataIndex: 'status',
      key: 'status',
      render: (value: string) => {
        const meta = statusMeta[value] ?? statusMeta.inactive
        return <Tag color={meta.color}>{meta.text}</Tag>
      },
    },
    {
      title: 'Договор',
      key: 'contract',
      render: (_: unknown, row: ServiceObject) => row.contract?.number ?? '—',
    },
    {
      title: 'Действие',
      key: 'action',
      render: (_: unknown, row: ServiceObject) => (
        <Button size="small" onClick={() => openCard(row)}>
          Открыть
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Card>
        <Space wrap>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Объекты
          </Typography.Title>
          <Select
            allowClear
            placeholder="Тип объекта"
            options={typeOptions}
            value={typeFilter}
            onChange={setTypeFilter}
            style={{ width: 170 }}
          />
          <Select
            allowClear
            placeholder="Статус"
            options={statusOptions}
            value={statusFilter}
            onChange={setStatusFilter}
            style={{ width: 160 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            Добавить объект
          </Button>
        </Space>
      </Card>

      <Card style={{ marginTop: 16 }}>
        <Table rowKey="id" columns={columns} dataSource={rows} pagination={{ pageSize: 10 }} />
      </Card>

      <Modal
        title="Новый объект"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        okText="Сохранить"
        cancelText="Отмена"
      >
        <Form form={form} layout="vertical" onFinish={createObject} initialValues={{ type: 'gym' }}>
          <Form.Item name="name" label="Название" rules={[{ required: true }]}>
            <Input placeholder="Название объекта" />
          </Form.Item>
          <Form.Item name="address" label="Адрес" rules={[{ required: true }]}>
            <Input placeholder="Адрес" />
          </Form.Item>
          <Form.Item name="type" label="Тип" rules={[{ required: true }]}>
            <Select options={typeOptions} />
          </Form.Item>
          <Form.Item
            name="area_sqm"
            label="Площадь"
            rules={[
              { required: true },
              { pattern: /^\d+(?:[.,]\d{1,2})?$/, message: 'Введите число, не более 2 знаков после запятой' },
            ]}
          >
            <Input inputMode="decimal" placeholder="Площадь, м²" />
          </Form.Item>
          <Form.Item name="contract_number" label="Договор">
            <Input placeholder="Номер договора" />
          </Form.Item>
          <Form.Item
            name="monthly_amount"
            label="Абонентская плата"
            rules={[
              { pattern: /^\d+(?:[.,]\d{1,2})?$/, message: 'Введите сумму, не более 2 знаков после запятой' },
            ]}
          >
            <Input inputMode="decimal" placeholder="Абонплата, ₽/мес" />
          </Form.Item>
          <Form.Item name="risk_points" label="Точки риска">
            <Input placeholder="кухня, подвал, раздевалка" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title="Карточка объекта"
        size="large"
        open={selected !== null}
        onClose={closeCard}
      >
        {selected ? (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="Название">{selected.name}</Descriptions.Item>
              <Descriptions.Item label="Адрес">{selected.address}</Descriptions.Item>
              <Descriptions.Item label="Тип">{typeLabel(selected.type)}</Descriptions.Item>
              <Descriptions.Item label="Площадь">{selected.area_sqm} м²</Descriptions.Item>
              <Descriptions.Item label="Статус">
                {statusMeta[selected.status]?.text ?? selected.status}
              </Descriptions.Item>
              <Descriptions.Item label="Последняя обработка">
                {dateLabel(selected.last_treatment_date)}
              </Descriptions.Item>
              <Descriptions.Item label="Следующая обработка">
                {dateLabel(selected.next_treatment_date)}
              </Descriptions.Item>
              <Descriptions.Item label="Точки риска">
                {selected.risk_points.length
                  ? selected.risk_points.map((point) => <Tag key={point}>{point}</Tag>)
                  : '—'}
              </Descriptions.Item>
            </Descriptions>

            <Card title="Документы" size="small">
              {selected.contract ? (
                <Space orientation="vertical">
                  <Typography.Text strong>Договор {selected.contract.number}</Typography.Text>
                  <Typography.Text>{moneyLabel(selected.contract.monthly_amount)}</Typography.Text>
                </Space>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Договор не указан" />
              )}
            </Card>

            <Card title="История обработок" size="small">
              {treatments.length ? (
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={treatments}
                  columns={[
                    {
                      title: 'Дата',
                      dataIndex: 'performed_at',
                      render: (value: string) => value.slice(0, 16).replace('T', ' '),
                    },
                    { title: 'Мастер', dataIndex: 'performed_by' },
                    { title: 'Комментарий', dataIndex: 'notes' },
                  ]}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Обработок пока нет" />
              )}
            </Card>
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
