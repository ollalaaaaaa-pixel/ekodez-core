import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Col, DatePicker, Empty, Flex, FloatButton, Input, InputNumber,
  Modal, Popconfirm, Row, Select, Space, Spin, Tag, Typography, message,
} from 'antd'
import { ArrowRightOutlined, CloseOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import './DayPage.css'

const API = 'http://127.0.0.1:8000'
const INCOME_CATEGORIES = [
  'Химчистка', 'Дезинсекция', 'Дератизация', 'Дезинфекция',
  'Обработка от клещей', 'Клининг', 'Юридические клиенты',
  'Доход от агрегаторов', 'Другие работы',
] as const
const CHANNELS = ['Яндекс', '2ГИС', 'Авито', 'ВК', 'Сарафан', 'Прочее'] as const

type Kind = 'income' | 'expense'
type CategoryTotal = { kind: Kind; category: string; total: string }
type ExpenseCategory = { id: number; name: string }
type DayEntry = {
  id: number; kind: Kind; category: string; amount: string; description: string | null
  entered_by: string; time: string; source: string; can_delete: boolean
}
type DayData = {
  income_total: string; expense_total: string; balance: string
  categories: CategoryTotal[]; entries: DayEntry[]
}
type Draft = {
  kind: Kind; category: string; channel: string; amount: number | null; comment: string
}
type CategoryTarget = 'desktop' | 'mobile'

const emptyDraft = (kind: Kind): Draft => ({
  kind, category: '', channel: '', amount: null, comment: '',
})
const money = (value: string | number) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(value))

export default function DayPage({ onNavigate }: { onNavigate: (screen: string) => void }) {
  const today = dayjs().format('YYYY-MM-DD')
  const [selectedDate, setSelectedDate] = useState(today)
  const [enteredBy, setEnteredBy] = useState('Артем')
  const [data, setData] = useState<DayData | null>(null)
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([])
  const [newLeads, setNewLeads] = useState(0)
  const [reviewCount, setReviewCount] = useState(0)
  const [telegramStarted, setTelegramStarted] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [incomeDraft, setIncomeDraft] = useState<Draft>(emptyDraft('income'))
  const [expenseDraft, setExpenseDraft] = useState<Draft>(emptyDraft('expense'))
  const [mobileOpen, setMobileOpen] = useState(false)
  const [mobileDraft, setMobileDraft] = useState<Draft | null>(null)
  const [categoryModalOpen, setCategoryModalOpen] = useState(false)
  const [categoryTarget, setCategoryTarget] = useState<CategoryTarget>('desktop')
  const [newCategoryName, setNewCategoryName] = useState('')
  const [creatingCategory, setCreatingCategory] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const responses = await Promise.all([
        fetch(`${API}/api/day?date=${selectedDate}`), fetch(`${API}/api/leads`),
        fetch(`${API}/api/finance/summary`), fetch(`${API}/health`),
        fetch(`${API}/api/expense-categories`),
      ])
      if (responses.some((response) => !response.ok)) throw new Error('Не удалось загрузить дневник')
      const [dayData, leads, summary, health, expenses] = await Promise.all(
        responses.map((response) => response.json()),
      )
      setData(dayData)
      setNewLeads(leads.filter((lead: { status: string }) => lead.status === 'new').length)
      setReviewCount(summary.review_count ?? 0)
      setTelegramStarted(health.telegram === 'started')
      setExpenseCategories(expenses)
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [selectedDate])

  useEffect(() => { void load() }, [load])

  const totals = useMemo(() => {
    const result = new Map<string, string>()
    data?.categories.forEach((item) => result.set(`${item.kind}:${item.category}`, item.total))
    return result
  }, [data])

  const saveDraft = async (draft: Draft, source: CategoryTarget) => {
    if (!draft.category) { message.warning('Выберите категорию'); return }
    if (!draft.amount || draft.amount <= 0) { message.warning('Введите сумму больше нуля'); return }
    setSaving(true)
    try {
      const response = await fetch(`${API}/api/day/entry`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: draft.kind, category: draft.category, amount: draft.amount,
          channel: draft.kind === 'income' ? draft.channel || null : null,
          comment: draft.comment || null, entered_by: enteredBy, date: selectedDate,
        }),
      })
      if (!response.ok) throw new Error('Не удалось сохранить запись')
      if (source === 'mobile') { setMobileDraft(null); setMobileOpen(false) }
      else if (draft.kind === 'income') setIncomeDraft(emptyDraft('income'))
      else setExpenseDraft(emptyDraft('expense'))
      await load()
      message.success('Запись добавлена')
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const openCategoryModal = (target: CategoryTarget) => {
    setCategoryTarget(target)
    setNewCategoryName('')
    setCategoryModalOpen(true)
  }

  const createExpenseCategory = async () => {
    const name = newCategoryName.trim()
    if (!name) { message.warning('Введите название категории'); return }
    setCreatingCategory(true)
    try {
      const response = await fetch(`${API}/api/expense-categories`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.detail === 'category already exists'
          ? 'Такая категория уже существует' : 'Не удалось создать категорию')
      }
      const created: ExpenseCategory = await response.json()
      setExpenseCategories((current) => [...current, created].sort((a, b) => a.id - b.id))
      if (categoryTarget === 'mobile') {
        setMobileDraft((current) => current ? { ...current, category: created.name } : current)
      } else {
        setExpenseDraft((current) => ({ ...current, category: created.name }))
      }
      setCategoryModalOpen(false)
      message.success(`Категория «${created.name}» добавлена`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Ошибка создания')
    } finally {
      setCreatingCategory(false)
    }
  }

  const removeEntry = async (id: number) => {
    const response = await fetch(`${API}/api/transactions/${id}`, { method: 'DELETE' })
    if (!response.ok) { message.error('Эту запись удалить нельзя'); return }
    await load(); message.success('Запись удалена')
  }

  const categoryCard = (
    kind: Kind, title: string, categories: string[], draft: Draft,
    setDraft: (draft: Draft) => void,
  ) => (
    <Card className={`day-category-card day-${kind}`} title={title}>
      <div className="day-entry-form">
        <Select className="day-category-select" showSearch optionFilterProp="label"
          placeholder="Выберите категорию" value={draft.category || undefined}
          onChange={(category) => setDraft({ ...draft, category })}
          options={categories.map((category) => ({ value: category, label: category }))} />
        {kind === 'income' && <Select className="day-channel-select" allowClear
          placeholder="Не указан" value={draft.channel || undefined}
          onChange={(channel) => setDraft({ ...draft, channel: channel ?? '' })}
          options={CHANNELS.map((channel) => ({ value: channel, label: channel }))} />}
        {kind === 'expense' && <Button className="day-new-category"
          icon={<PlusOutlined />} onClick={() => openCategoryModal('desktop')}>Новая категория</Button>}
        <InputNumber className="day-amount-input" min={0} precision={2}
          placeholder="Сумма" value={draft.amount}
          onChange={(amount) => setDraft({ ...draft, amount })} />
        <Input className="day-comment-input" placeholder="Комментарий"
          value={draft.comment} onChange={(event) => setDraft({ ...draft, comment: event.target.value })} />
        <Button type="primary" loading={saving} onClick={() => void saveDraft(draft, 'desktop')}>Сохранить</Button>
      </div>
      <div className="day-category-totals">
        {categories.map((category) => <Flex className="day-category-row" key={category}
          align="center" justify="space-between" gap={12}>
          <span className="day-category-name">{category}</span>
          <strong>{money(totals.get(`${kind}:${category}`) ?? 0)} ₽</strong>
        </Flex>)}
      </div>
    </Card>
  )

  const balance = Number(data?.balance ?? 0)
  const expenseNames = expenseCategories.map((category) => category.name)
  const mobileCategories = mobileDraft?.kind === 'income' ? [...INCOME_CATEGORIES] : expenseNames

  return (
    <Spin spinning={loading}>
      <div className="day-page">
        <Flex className="day-toolbar" justify="space-between" align="center" gap={12} wrap>
          <Space wrap>
            <DatePicker allowClear={false} value={dayjs(selectedDate)} format="DD.MM.YYYY"
              onChange={(value) => value && setSelectedDate(value.format('YYYY-MM-DD'))} />
            <Select aria-label="Кто внёс запись" value={enteredBy} onChange={setEnteredBy}
              options={['Артем', 'Алексей'].map((value) => ({ value, label: `Кто: ${value}` }))} />
          </Space>
          <Tag color={telegramStarted ? 'success' : 'error'}>TG: {telegramStarted ? 'работает' : 'не запущен'}</Tag>
        </Flex>

        <Card className={`day-total-card ${balance >= 0 ? 'positive' : 'negative'}`}>
          <Typography.Text className="day-total-label">ИТОГ ДНЯ</Typography.Text>
          <div className="day-balance">{balance >= 0 ? '+' : '−'}{money(Math.abs(balance))} ₽</div>
          <Typography.Text type="secondary">заработали {money(data?.income_total ?? 0)} ₽ − потратили {money(data?.expense_total ?? 0)} ₽</Typography.Text>
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={12}>{categoryCard('income', 'Заработали сегодня', [...INCOME_CATEGORIES], incomeDraft, setIncomeDraft)}</Col>
          <Col xs={24} xl={12}>{categoryCard('expense', 'Потратили сегодня', expenseNames, expenseDraft, setExpenseDraft)}</Col>
        </Row>

        <Card className="day-entries-card" title="Записи дня">
          {!data?.entries.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Записей пока нет" /> : data.entries.map((entry) => (
            <Flex className="day-entry" key={entry.id} align="center" justify="space-between" gap={12}>
              <div className="day-entry-main"><Space wrap size={6}>
                <Typography.Text type="secondary">{entry.time}</Typography.Text><strong>{entry.category}</strong>
                <Typography.Text className={entry.kind === 'income' ? 'income-value' : 'expense-value'}>
                  {entry.kind === 'income' ? '+' : '−'}{money(entry.amount)} ₽
                </Typography.Text></Space>
                <div className="day-entry-note">{entry.description || 'Без комментария'} · {entry.entered_by}</div>
              </div>
              {entry.can_delete && <Popconfirm title="Удалить запись?" description="Это действие нельзя отменить."
                okText="Удалить" cancelText="Нет" onConfirm={() => void removeEntry(entry.id)}>
                <Button danger aria-label="Удалить запись" icon={<CloseOutlined />} />
              </Popconfirm>}
            </Flex>))}
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} md={12}><Button className="day-action-button" block onClick={() => onNavigate('leads')}>Новые заявки {newLeads} <ArrowRightOutlined /></Button></Col>
          <Col xs={24} md={12}><Button className="day-action-button" block onClick={() => onNavigate('finance')}>На проверку {reviewCount} <ArrowRightOutlined /></Button></Col>
        </Row>
      </div>

      <FloatButton className="day-mobile-float" type="primary" icon={<PlusOutlined />} tooltip="Добавить запись"
        onClick={() => { setMobileDraft(null); setMobileOpen(true) }} />
      <Modal title="Добавить запись" open={mobileOpen} footer={null} onCancel={() => setMobileOpen(false)}>
        {!mobileDraft ? <div className="day-mobile-grid">
          <Button type="primary" onClick={() => setMobileDraft(emptyDraft('income'))}>Заработали</Button>
          <Button danger onClick={() => setMobileDraft(emptyDraft('expense'))}>Потратили</Button>
        </div> : <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Select className="day-category-select" showSearch optionFilterProp="label" placeholder="Выберите категорию"
            value={mobileDraft.category || undefined}
            onChange={(category) => setMobileDraft({ ...mobileDraft, category })}
            options={mobileCategories.map((category) => ({ value: category, label: category }))} />
          {mobileDraft.kind === 'income' && <Select className="day-channel-select" allowClear
            placeholder="Не указан" value={mobileDraft.channel || undefined}
            onChange={(channel) => setMobileDraft({ ...mobileDraft, channel: channel ?? '' })}
            options={CHANNELS.map((channel) => ({ value: channel, label: channel }))} />}
          {mobileDraft.kind === 'expense' && <Button block className="day-new-category" icon={<PlusOutlined />}
            onClick={() => openCategoryModal('mobile')}>Новая категория</Button>}
          <InputNumber className="day-mobile-amount" min={0} precision={2} placeholder="Сумма"
            value={mobileDraft.amount} onChange={(amount) => setMobileDraft({ ...mobileDraft, amount })} />
          <Input.TextArea rows={3} placeholder="Комментарий" value={mobileDraft.comment}
            onChange={(event) => setMobileDraft({ ...mobileDraft, comment: event.target.value })} />
          <Button block type="primary" loading={saving} onClick={() => void saveDraft(mobileDraft, 'mobile')}>Сохранить</Button>
        </Space>}
      </Modal>

      <Modal title="Новая категория расходов" open={categoryModalOpen} footer={null}
        onCancel={() => setCategoryModalOpen(false)}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Input autoFocus className="day-new-category-input" maxLength={100}
            placeholder="Например: Аренда склада" value={newCategoryName}
            onChange={(event) => setNewCategoryName(event.target.value)}
            onPressEnter={() => void createExpenseCategory()} />
          <Button block type="primary" loading={creatingCategory}
            onClick={() => void createExpenseCategory()}>Сохранить</Button>
        </Space>
      </Modal>
    </Spin>
  )
}
