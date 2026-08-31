import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
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
import { ExperimentOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import './InventoryPage.css'

const API = 'http://127.0.0.1:8000'

type Inventory = {
  id: number
  chemical_name: string
  quantity: string
  initial_quantity: string
  unit: string
  batch_number: string
  expiry_date: string
  supplier: string
  low_stock: boolean
}

type ServiceObject = { id: number; name: string }

type ChemicalUsage = {
  id: number
  inventory_id: number
  chemical_name: string
  quantity_used: string
  unit: string
}

type Treatment = {
  id: number
  object_id: number
  chemicals_used: ChemicalUsage[]
  performed_at: string
  performed_by: string
  notes: string | null
}

type InventoryForm = {
  chemical_name: string
  quantity: string
  unit: string
  batch_number: string
  expiry_date: string
  supplier: string
}

type TreatmentForm = {
  object_id: number
  performed_at: string
  performed_by: string
  notes?: string
  chemicals_used: Array<{ inventory_id: number; quantity_used: string }>
}

const decimalString = (value: string) => {
  const normalized = value.trim().replace(',', '.')
  const [whole = '0', fraction = ''] = normalized.split('.')
  return `${whole}.${fraction.padEnd(3, '0').slice(0, 3)}`
}

const decimalRule = {
  pattern: /^\d+(?:[.,]\d{1,3})?$/,
  message: 'Введите число, не более 3 знаков после запятой',
}

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

export default function InventoryPage() {
  const [inventory, setInventory] = useState<Inventory[]>([])
  const [treatments, setTreatments] = useState<Treatment[]>([])
  const [objects, setObjects] = useState<ServiceObject[]>([])
  const [search, setSearch] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const [inventoryOpen, setInventoryOpen] = useState(false)
  const [treatmentOpen, setTreatmentOpen] = useState(false)
  const [inventoryForm] = Form.useForm<InventoryForm>()
  const [treatmentForm] = Form.useForm<TreatmentForm>()
  const isMobile = useIsMobile()

  const loadInventory = useCallback(async () => {
    const query = new URLSearchParams()
    if (search.trim()) query.set('search', search.trim())
    if (lowOnly) query.set('low_stock', 'true')
    const suffix = query.size ? `?${query.toString()}` : ''
    const response = await fetch(`${API}/api/inventory${suffix}`)
    if (!response.ok) throw new Error('inventory request failed')
    setInventory(await response.json())
  }, [lowOnly, search])

  const loadRelated = useCallback(async () => {
    const [treatmentResponse, objectResponse] = await Promise.all([
      fetch(`${API}/api/treatments`),
      fetch(`${API}/api/objects`),
    ])
    if (!treatmentResponse.ok || !objectResponse.ok) throw new Error('related request failed')
    setTreatments(await treatmentResponse.json())
    setObjects(await objectResponse.json())
  }, [])

  useEffect(() => {
    loadInventory().catch(() => message.error('Не удалось загрузить склад'))
  }, [loadInventory])

  useEffect(() => {
    loadRelated().catch(() => message.error('Не удалось загрузить историю'))
  }, [loadRelated])

  const createInventory = async (values: InventoryForm) => {
    const response = await fetch(`${API}/api/inventory`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...values, quantity: decimalString(values.quantity) }),
    })
    if (!response.ok) {
      message.error('Не удалось сохранить партию')
      return
    }
    setInventoryOpen(false)
    inventoryForm.resetFields()
    await loadInventory()
  }

  const createTreatment = async (values: TreatmentForm) => {
    const response = await fetch(`${API}/api/treatments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...values,
        chemicals_used: values.chemicals_used.map((row) => ({
          inventory_id: row.inventory_id,
          quantity_used: decimalString(row.quantity_used),
        })),
      }),
    })
    if (!response.ok) {
      message.error(response.status === 409 ? 'Недостаточно препарата' : 'Не удалось списать')
      return
    }
    setTreatmentOpen(false)
    treatmentForm.resetFields()
    await Promise.all([loadInventory(), loadRelated()])
  }

  const lowCount = inventory.filter((row) => row.low_stock).length
  const objectNames = new Map(objects.map((row) => [row.id, row.name]))

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <Card>
        <Space wrap>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Склад
          </Typography.Title>
          <Input
            allowClear
            placeholder="Поиск по препарату или партии"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            style={{ width: 'min(260px, 100%)' }}
          />
          <Checkbox checked={lowOnly} onChange={(event) => setLowOnly(event.target.checked)}>
            Только низкий остаток
          </Checkbox>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setInventoryOpen(true)}>
            Добавить препарат
          </Button>
          <Button icon={<ExperimentOutlined />} onClick={() => setTreatmentOpen(true)}>
            Списать на обработку
          </Button>
        </Space>
      </Card>

      {lowCount > 0 ? (
        <Alert
          type="warning"
          showIcon
          title={`Низкий остаток: ${lowCount}`}
          description="Осталось менее 10% исходного количества партии"
        />
      ) : null}

      <Card title="Остатки препаратов">
        {isMobile ? (
          <div className="inventory-mobile-list">
            {inventory.map((row) => (
              <Card key={row.id} data-testid="inventory-mobile-card" size="small" title={row.chemical_name}>
                <div className="inventory-mobile-details">
                  <strong>{row.quantity} {row.unit}</strong>
                  <span>Партия: {row.batch_number}</span>
                  <span>Годен до: {row.expiry_date}</span>
                  <span>Поставщик: {row.supplier}</span>
                  {row.low_stock ? <Tag color="red">Низкий остаток</Tag> : <Tag color="green">В норме</Tag>}
                </div>
              </Card>
            ))}
          </div>
        ) : <div data-testid="inventory-desktop-table"><Table
          rowKey="id"
          dataSource={inventory}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: 'Препарат', dataIndex: 'chemical_name' },
            {
              title: 'Остаток',
              render: (_: unknown, row: Inventory) => `${row.quantity} ${row.unit}`,
            },
            { title: 'Партия', dataIndex: 'batch_number' },
            { title: 'Годен до', dataIndex: 'expiry_date' },
            { title: 'Поставщик', dataIndex: 'supplier' },
            {
              title: 'Статус',
              render: (_: unknown, row: Inventory) =>
                row.low_stock ? <Tag color="red">Низкий остаток</Tag> : <Tag color="green">В норме</Tag>,
            },
          ]}
        /></div>}
      </Card>

      <Card title="История списаний">
        {isMobile ? (
          <div className="inventory-mobile-list">
            {treatments.map((row) => (
              <Card key={row.id} data-testid="treatment-mobile-card" size="small" title={row.performed_at.slice(0, 16).replace('T', ' ')}>
                <div className="inventory-mobile-details">
                  <strong>{objectNames.get(row.object_id) ?? `Объект #${row.object_id}`}</strong>
                  <span>Мастер: {row.performed_by}</span>
                  {row.chemicals_used.map((usage) => (
                    <div key={usage.id}>
                      <span>{usage.chemical_name}</span> — <span>{usage.quantity_used} {usage.unit}</span>
                    </div>
                  ))}
                  {row.notes ? <span>{row.notes}</span> : null}
                </div>
              </Card>
            ))}
          </div>
        ) : <div data-testid="treatment-desktop-table"><Table
          rowKey="id"
          dataSource={treatments}
          pagination={{ pageSize: 10 }}
          columns={[
            {
              title: 'Дата',
              dataIndex: 'performed_at',
              render: (value: string) => value.slice(0, 16).replace('T', ' '),
            },
            {
              title: 'Объект',
              dataIndex: 'object_id',
              render: (value: number) => objectNames.get(value) ?? `Объект #${value}`,
            },
            { title: 'Мастер', dataIndex: 'performed_by' },
            {
              title: 'Препараты',
              render: (_: unknown, row: Treatment) => (
                <Space orientation="vertical" size={0}>
                  {row.chemicals_used.map((usage) => (
                    <span key={usage.id}>
                      {usage.chemical_name} — <span>{usage.quantity_used} {usage.unit}</span>
                    </span>
                  ))}
                </Space>
              ),
            },
            { title: 'Комментарий', dataIndex: 'notes' },
          ]}
        /></div>}
      </Card>

      <Modal
        title="Новая партия"
        open={inventoryOpen}
        onCancel={() => setInventoryOpen(false)}
        onOk={() => inventoryForm.submit()}
        okText="Сохранить"
        cancelText="Отмена"
      >
        <Form form={inventoryForm} layout="vertical" onFinish={createInventory}>
          <Form.Item name="chemical_name" label="Препарат" rules={[{ required: true }]}>
            <Input placeholder="Название препарата" />
          </Form.Item>
          <Form.Item name="quantity" label="Количество" rules={[{ required: true }, decimalRule]}>
            <Input inputMode="decimal" placeholder="Количество" />
          </Form.Item>
          <Form.Item name="unit" label="Единица" rules={[{ required: true }]}>
            <Input placeholder="Единица" />
          </Form.Item>
          <Form.Item name="batch_number" label="Партия" rules={[{ required: true }]}>
            <Input placeholder="Номер партии" />
          </Form.Item>
          <Form.Item name="expiry_date" label="Срок годности" rules={[{ required: true }]}>
            <Input type="date" placeholder="Срок годности" />
          </Form.Item>
          <Form.Item name="supplier" label="Поставщик" rules={[{ required: true }]}>
            <Input placeholder="Поставщик" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Списание на обработку"
        open={treatmentOpen}
        onCancel={() => setTreatmentOpen(false)}
        onOk={() => treatmentForm.submit()}
        okText="Списать"
        cancelText="Отмена"
        width={680}
      >
        <Form
          form={treatmentForm}
          layout="vertical"
          onFinish={createTreatment}
          initialValues={{ chemicals_used: [{}] }}
        >
          <Form.Item name="object_id" label="Объект" rules={[{ required: true }]}>
            <Select options={objects.map((row) => ({ value: row.id, label: row.name }))} />
          </Form.Item>
          <Form.Item name="performed_at" label="Дата и время" rules={[{ required: true }]}>
            <Input type="datetime-local" />
          </Form.Item>
          <Form.Item name="performed_by" label="Мастер" rules={[{ required: true }]}>
            <Input placeholder="Имя мастера" />
          </Form.Item>
          <Form.List name="chemicals_used">
            {(fields, { add, remove }) => (
              <Space orientation="vertical" style={{ width: '100%' }}>
                {fields.map((field) => (
                  <Space key={field.key} align="start">
                    <Form.Item
                      {...field}
                      name={[field.name, 'inventory_id']}
                      rules={[{ required: true, message: 'Выберите препарат' }]}
                    >
                      <Select
                        placeholder="Препарат"
                        style={{ width: 280 }}
                        options={inventory.map((row) => ({
                          value: row.id,
                          label: `${row.chemical_name} (${row.quantity} ${row.unit})`,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item
                      {...field}
                      name={[field.name, 'quantity_used']}
                      rules={[{ required: true }, decimalRule]}
                    >
                      <Input inputMode="decimal" placeholder="Количество" style={{ width: 150 }} />
                    </Form.Item>
                    {fields.length > 1 ? (
                      <Button icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} />
                    ) : null}
                  </Space>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add()}>
                  Добавить препарат
                </Button>
              </Space>
            )}
          </Form.List>
          <Form.Item name="notes" label="Комментарий" style={{ marginTop: 16 }}>
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
