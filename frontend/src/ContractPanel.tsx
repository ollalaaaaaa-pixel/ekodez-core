import { useEffect, useState } from 'react'
import { Button, Card, Empty, Form, Input, Modal, Select, Space, Tag, Typography, message } from 'antd'

const API = 'http://127.0.0.1:8000'

export type ContractSummary = {
  id: number
  number: string
  price: string
  contract_date: string | null
  periodicity: 'monthly' | 'semiannual' | 'custom' | null
  service_months: number[]
  payment_term_business_days: number
  default_ksp: number
  default_derat_glue: number
  default_baits: number
  default_disinsection_glue: number
  start_date: string | null
  end_date: string | null
}

export type ObjectSummary = {
  id: number
  name: string
  address: string
  type: string
  area_sqm: string
  contract: ContractSummary | null
  risk_points: string[]
  last_treatment_date: string | null
  next_treatment_date: string | null
  status: string
}

type TimelineEvent = { date?: string; type?: string; month?: string }
type Transaction = {
  id: number
  operation_date: string
  amount: string
  kind: string
  review_required: boolean
  object_id: number | null
  description: string | null
}
type Period = {
  id: number
  invoice_number: string | null
  paid_service_due: boolean
  price_snapshot: string | null
  file_manifest: Array<{ version: number; kind: string; name: string }>
}

const periodicityOptions = [
  { value: 'monthly', label: 'Ежемесячно' },
  { value: 'semiannual', label: '2 раза в год' },
  { value: 'custom', label: 'Своя' },
]
const monthOptions = Array.from({ length: 12 }, (_, index) => ({
  value: index + 1,
  label: new Intl.DateTimeFormat('ru-RU', { month: 'long' }).format(new Date(2026, index, 1)),
}))

const priceLabel = (value: string, periodicity: ContractSummary['periodicity']) => {
  const amount = Number(value)
  const formatted = Number.isFinite(amount)
    ? new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(amount)
    : value
  return `${formatted} ₽${periodicity === 'monthly' ? '/мес' : ''}`
}

const today = new Date().toISOString().slice(0, 10)
const currentMonth = today.slice(0, 7)

export default function ContractPanel({
  object,
  onObjectUpdated,
}: {
  object: ObjectSummary
  onObjectUpdated: (value: ObjectSummary) => void
}) {
  const [contractOpen, setContractOpen] = useState(false)
  const [billingOpen, setBillingOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [packageOpen, setPackageOpen] = useState(false)
  const [timeline, setTimeline] = useState<TimelineEvent[]>([])
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [period, setPeriod] = useState<Period | null>(null)
  const [contractForm] = Form.useForm()
  const [billingForm] = Form.useForm()
  const [profileForm] = Form.useForm()
  const [packageForm] = Form.useForm()
  const periodicity = Form.useWatch('periodicity', contractForm)

  const loadTimeline = () => {
    fetch(`${API}/api/objects/${object.id}/contract-timeline`)
      .then((response) => (response.ok ? response.json() : []))
      .then(setTimeline)
  }

  useEffect(loadTimeline, [object.id])

  const openContract = () => {
    contractForm.resetFields()
    if (object.contract) {
      contractForm.setFieldsValue({
        ...object.contract,
        price: object.contract.price,
      })
    }
    setContractOpen(true)
  }

  const saveContract = async () => {
    const values = await contractForm.validateFields()
    const response = await fetch(`${API}/api/objects/${object.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contract: {
          number: values.number,
          contract_date: values.contract_date || null,
          price: String(values.price).replace(',', '.'),
          periodicity: values.periodicity,
          service_months: values.periodicity === 'monthly' ? [] : values.service_months,
          payment_term_business_days: 5,
          default_ksp: 5,
          default_derat_glue: 5,
          default_baits: 5,
          default_disinsection_glue: 6,
        },
      }),
    })
    if (!response.ok) return message.error('Не удалось сохранить договор')
    const updated = await response.json()
    onObjectUpdated(updated)
    setContractOpen(false)
    message.success('Договор сохранён')
  }

  const openBilling = async () => {
    billingForm.resetFields()
    const response = await fetch(`${API}/api/objects/${object.id}/billing-client?show_pii=true`)
    if (response.ok) billingForm.setFieldsValue(await response.json())
    setBillingOpen(true)
  }

  const saveBilling = async () => {
    const values = await billingForm.validateFields()
    const response = await fetch(`${API}/api/objects/${object.id}/billing-client`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    })
    if (!response.ok) return message.error('Не удалось сохранить реквизиты')
    setBillingOpen(false)
    message.success('Реквизиты сохранены')
  }

  const saveDocumentProfile = async () => {
    const values = await profileForm.validateFields()
    const response = await fetch(`${API}/api/document-profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    })
    if (!response.ok) return message.error('Не удалось сохранить реквизиты ЭКОДЕЗ')
    profileForm.resetFields()
    setProfileOpen(false)
    message.success('Реквизиты ЭКОДЕЗ сохранены в зашифрованном виде')
  }

  const openPackage = async () => {
    if (!object.contract) return
    packageForm.resetFields()
    packageForm.setFieldsValue({
      month: currentMonth,
      inspection_date: today,
      ksp_count: object.contract.default_ksp,
      derat_glue_count: object.contract.default_derat_glue,
      bait_count: object.contract.default_baits,
      rodents_caught: 0,
      deratization_result: 'not_required',
      disinsection_glue_count: object.contract.default_disinsection_glue,
      insects_caught: 0,
      disinsection_result: 'not_required',
      inspection_status: 'draft',
      infestation_degree: 'начальная',
      work_act_status: 'draft',
      invoice_date: today,
    })
    const response = await fetch(`${API}/api/transactions`)
    const rows = response.ok ? ((await response.json()) as Transaction[]) : []
    setTransactions(
      rows.filter(
        (row) => row.kind === 'income' && !row.review_required && row.object_id === object.id,
      ),
    )
    setPeriod(null)
    setPackageOpen(true)
  }

  const savePackage = async (generate: boolean) => {
    if (!object.contract) return
    const values = await packageForm.validateFields()
    const reportResponse = await fetch(
      `${API}/api/contracts/${object.contract.id}/inspection-reports/${values.month}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          inspection_date: values.inspection_date,
          control_date: values.control_date || null,
          ksp_count: Number(values.ksp_count),
          derat_glue_count: Number(values.derat_glue_count),
          bait_count: Number(values.bait_count),
          rodents_caught: Number(values.rodents_caught),
          deratization_result: values.deratization_result,
          disinsection_glue_count: Number(values.disinsection_glue_count),
          insects_caught: Number(values.insects_caught),
          disinsection_result: values.disinsection_result,
          status: values.inspection_status,
          signed_at:
            values.inspection_status === 'signed' ? new Date().toISOString() : null,
        }),
      },
    )
    if (!reportResponse.ok) return message.error('Не удалось сохранить обследование')
    const periodResponse = await fetch(
      `${API}/api/contracts/${object.contract.id}/periods/${values.month}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preparations: values.preparations || null,
          infestation_degree: values.infestation_degree,
          extra_services: (values.extra_services || '')
            .split(',')
            .map((item: string) => item.trim())
            .filter(Boolean),
          invoice_number: values.invoice_number || undefined,
          invoice_date: values.invoice_date || null,
          work_act_status: values.work_act_status,
          work_act_signed_at:
            values.work_act_status === 'signed' ? new Date().toISOString() : null,
          transaction_id: values.transaction_id || null,
        }),
      },
    )
    if (!periodResponse.ok) return message.error('Не удалось сохранить период')
    let saved = (await periodResponse.json()) as Period
    if (generate) {
      const generated = await fetch(`${API}/api/contract-periods/${saved.id}/generate`, {
        method: 'POST',
      })
      if (!generated.ok) return message.error('Не удалось сформировать DOCX')
      saved = await generated.json()
      message.success('Пакет сформирован')
    } else {
      message.success('Черновик сохранён')
    }
    setPeriod(saved)
    packageForm.setFieldValue('invoice_number', saved.invoice_number)
    loadTimeline()
  }

  return (
    <>
      <Card title="Документы" size="small">
        <Space orientation="vertical" style={{ width: '100%' }}>
          {object.contract ? (
            <>
              <Typography.Text strong>Договор {object.contract.number}</Typography.Text>
              <Typography.Text>
                {priceLabel(object.contract.price, object.contract.periodicity)}
              </Typography.Text>
              <Typography.Text>
                {periodicityOptions.find((item) => item.value === object.contract?.periodicity)?.label ??
                  'Периодичность не настроена'}
              </Typography.Text>
            </>
          ) : (
            <Typography.Text type="secondary">Договор не указан</Typography.Text>
          )}
          <Space wrap>
            <Button onClick={openContract}>Настроить договор</Button>
            <Button onClick={openBilling}>Плательщик и реквизиты</Button>
            <Button onClick={() => setProfileOpen(true)}>Реквизиты ЭКОДЕЗ</Button>
            {object.contract ? <Button type="primary" onClick={openPackage}>Пакет за месяц</Button> : null}
          </Space>
        </Space>
      </Card>

      <Card title="Акты и оплаты" size="small">
        {timeline.length ? (
          <Space orientation="vertical" size="small" style={{ width: '100%' }}>
            {timeline.map((item, index) => (
              <Space key={`${item.type}-${item.month}-${item.date}-${index}`} wrap>
                <Tag>{item.type ?? 'Событие'}</Tag>
                <span>{item.month?.slice(0, 7) ?? '—'}</span>
                <span>{item.date?.slice(0, 10) ?? '—'}</span>
              </Space>
            ))}
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Событий пока нет" />
        )}
      </Card>

      <Modal title="Договор" open={contractOpen} onCancel={() => setContractOpen(false)} onOk={saveContract} okText="Сохранить" forceRender>
        <Form form={contractForm} layout="vertical">
          <Form.Item name="number" label="Номер договора" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="contract_date" label="Дата договора"><Input type="date" /></Form.Item>
          <Form.Item name="price" label="Цена договора" rules={[{ required: true, message: 'Введите цену вручную' }, { pattern: /^\d+(?:[.,]\d{1,2})?$/, message: 'Введите сумму' }]}><Input inputMode="decimal" /></Form.Item>
          <Form.Item name="periodicity" label="Периодичность" rules={[{ required: true }]}><Select options={periodicityOptions} /></Form.Item>
          {periodicity && periodicity !== 'monthly' ? (
            <Form.Item name="service_months" label="Оплачиваемые месяцы" rules={[{ required: true }]}><Select mode="multiple" options={monthOptions} /></Form.Item>
          ) : null}
        </Form>
      </Modal>

      <Modal title="Плательщик и реквизиты" open={billingOpen} onCancel={() => setBillingOpen(false)} onOk={saveBilling} okText="Сохранить" forceRender>
        <Form form={billingForm} layout="vertical">
          <Form.Item name="client_type" label="Тип клиента" rules={[{ required: true }]}><Select options={[{ value: 'legal_entity', label: 'ООО' }, { value: 'sole_proprietor', label: 'ИП' }, { value: 'individual', label: 'Физлицо' }]} /></Form.Item>
          <Form.Item name="name" label="Наименование / ФИО" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="representative" label="Представитель"><Input /></Form.Item>
          <Form.Item name="representative_role" label="Должность"><Input /></Form.Item>
          <Form.Item name="phone" label="Телефон"><Input /></Form.Item>
          <Form.Item name="inn" label="ИНН"><Input /></Form.Item>
          <Form.Item name="kpp" label="КПП"><Input /></Form.Item>
          <Form.Item name="registration_number" label="ОГРН / ОГРНИП"><Input /></Form.Item>
          <Form.Item name="legal_address" label="Юридический адрес"><Input /></Form.Item>
          <Form.Item name="bank_details" label="Банковские реквизиты"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="Реквизиты ЭКОДЕЗ для документов" open={profileOpen} onCancel={() => setProfileOpen(false)} onOk={saveDocumentProfile} okText="Сохранить зашифрованно" forceRender>
        <Form form={profileForm} layout="vertical">
          <Form.Item name="executor_bank_details" label="Банковские реквизиты" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="executor_inn" label="ИНН исполнителя" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="executor_ogrnip" label="ОГРНИП исполнителя" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="tax_mode" label="Налоговый режим / НДС" rules={[{ required: true }]}><Input /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Пакет за месяц"
        open={packageOpen}
        onCancel={() => setPackageOpen(false)}
        footer={[
          <Button key="save" onClick={() => savePackage(false)}>Сохранить черновик</Button>,
          <Button key="generate" type="primary" onClick={() => savePackage(true)}>Сформировать DOCX</Button>,
        ]}
        width={760}
        forceRender
      >
        <Form form={packageForm} layout="vertical" className="contract-package-form">
          <Form.Item name="month" label="Месяц" rules={[{ required: true }]}><Input type="month" /></Form.Item>
          <Form.Item name="inspection_date" label="Дата обследования" rules={[{ required: true }]}><Input type="date" /></Form.Item>
          <Form.Item name="control_date" label="Контрольная дата"><Input type="date" /></Form.Item>
          <Form.Item name="ksp_count" label="КСП"><Input type="number" min={0} /></Form.Item>
          <Form.Item name="derat_glue_count" label="КЛ дератизация"><Input type="number" min={0} /></Form.Item>
          <Form.Item name="bait_count" label="Приманки"><Input type="number" min={0} /></Form.Item>
          <Form.Item name="rodents_caught" label="Заслежено / отловлено"><Input type="number" min={0} /></Form.Item>
          <Form.Item name="deratization_result" label="Результат дератизации"><Select options={[{ value: 'not_required', label: 'Не требуется' }, { value: 'required', label: 'Требуется и выполнена' }]} /></Form.Item>
          <Form.Item name="disinsection_glue_count" label="КЛ дезинсекция"><Input type="number" min={0} /></Form.Item>
          <Form.Item name="insects_caught" label="Отловлено насекомых"><Input type="number" min={0} /></Form.Item>
          <Form.Item name="disinsection_result" label="Результат дезинсекции"><Select options={[{ value: 'not_required', label: 'Не требуется' }, { value: 'required', label: 'Требуется и выполнена' }]} /></Form.Item>
          <Form.Item name="inspection_status" label="Статус акта осмотра"><Select options={[{ value: 'draft', label: 'Черновик' }, { value: 'signed', label: 'Подписан' }]} /></Form.Item>
          <Form.Item name="preparations" label="Препараты"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="infestation_degree" label="Степень заражения"><Input /></Form.Item>
          <Form.Item name="extra_services" label="Дополнительные услуги"><Input placeholder="Через запятую" /></Form.Item>
          <Form.Item name="invoice_number" label="Номер счёта"><Input placeholder="Система предложит следующий номер" /></Form.Item>
          <Form.Item name="invoice_date" label="Дата счёта"><Input type="date" /></Form.Item>
          <Form.Item name="work_act_status" label="Статус акта выполненных работ"><Select options={[{ value: 'draft', label: 'Черновик' }, { value: 'signed', label: 'Подписан' }]} /></Form.Item>
          <Form.Item name="transaction_id" label="Привязать оплату"><Select allowClear options={transactions.map((row) => ({ value: row.id, label: `${row.operation_date} · ${row.amount} ₽ · ${row.description ?? 'без комментария'}` }))} /></Form.Item>
        </Form>
        {period?.file_manifest?.length ? (
          <Space orientation="vertical" size="small">
            {period.file_manifest.map((item) => (
              <Space key={`${item.version}-${item.name}`}>
                <Tag>v{item.version}</Tag>
                <span>{item.name}</span>
                <Button
                  size="small"
                  href={`${API}/api/contract-periods/${period.id}/files/${encodeURIComponent(item.name)}`}
                  target="_blank"
                >
                  Открыть
                </Button>
              </Space>
            ))}
          </Space>
        ) : null}
      </Modal>
    </>
  )
}
