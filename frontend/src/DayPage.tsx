import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Col, DatePicker, Empty, Flex, FloatButton, Input, InputNumber,
  Modal, Popconfirm, Row, Select, Space, Spin, Tag, Typography, message,
} from 'antd'
import { ArrowRightOutlined, CloseOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import './DayPage.css'

const API = 'http://127.0.0.1:8000'
const INCOME_CATEGORIES = ['Химчистка', 'Дезинфекция', 'Другие работы']
const EXPENSE_CATEGORIES = ['Еда', 'Топливо и машина', 'Материалы', 'Другое']
type Kind = 'income' | 'expense'
type CategoryTotal = { kind: Kind; category: string; total: string }
type DayEntry = {
  id: number; kind: Kind; category: string; amount: string; description: string | null
  entered_by: string; time: string; source: string; can_delete: boolean
}
type DayData = {
  income_total: string; expense_total: string; balance: string
  categories: CategoryTotal[]; entries: DayEntry[]
}
type Draft = { kind: Kind; category: string; amount: number | null; comment: string }

const emptyDraft = (kind: Kind, category: string): Draft => ({ kind, category, amount: null, comment: '' })
const money = (value: string | number) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(value))

export default function DayPage({ onNavigate }: { onNavigate: (screen: string) => void }) {
  const today = dayjs().format('YYYY-MM-DD')
  const [selectedDate, setSelectedDate] = useState(today)
  const [enteredBy, setEnteredBy] = useState('Артем')
  const [data, setData] = useState<DayData | null>(null)
  const [newLeads, setNewLeads] = useState(0)
  const [reviewCount, setReviewCount] = useState(0)
  const [telegramStarted, setTelegramStarted] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [inlineDraft, setInlineDraft] = useState<Draft | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [mobileDraft, setMobileDraft] = useState<Draft | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [dayResponse, leadsResponse, summaryResponse, healthResponse] = await Promise.all([
        fetch(`${API}/api/day?date=${selectedDate}`), fetch(`${API}/api/leads`),
        fetch(`${API}/api/finance/summary`), fetch(`${API}/health`),
      ])
      if (!dayResponse.ok || !leadsResponse.ok || !summaryResponse.ok || !healthResponse.ok) {
        throw new Error('Не удалось загрузить дневник')
      }
      const [dayData, leads, summary, health] = await Promise.all([
        dayResponse.json(), leadsResponse.json(), summaryResponse.json(), healthResponse.json(),
      ])
      setData(dayData)
      setNewLeads(leads.filter((lead: { status: string }) => lead.status === 'new').length)
      setReviewCount(summary.review_count ?? 0)
      setTelegramStarted(health.telegram === 'started')
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

  const saveDraft = async (draft: Draft) => {
    if (!draft.amount || draft.amount <= 0) {
      message.warning('Введите сумму больше нуля')
      return
    }
    setSaving(true)
    try {
      const response = await fetch(`${API}/api/day/entry`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: draft.kind, category: draft.category, amount: draft.amount,
          comment: draft.comment || null, entered_by: enteredBy, date: selectedDate,
        }),
      })
      if (!response.ok) throw new Error('Не удалось сохранить запись')
      setInlineDraft(null); setMobileDraft(null); setMobileOpen(false)
      await load()
      message.success('Запись добавлена')
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const removeEntry = async (id: number) => {
    const response = await fetch(`${API}/api/transactions/${id}`, { method: 'DELETE' })
    if (!response.ok) { message.error('Эту запись удалить нельзя'); return }
    await load(); message.success('Запись удалена')
  }

  const categoryCard = (kind: Kind, title: string, categories: string[]) => (
    <Card className={`day-category-card day-${kind}`} title={title}>
      {categories.map((category) => {
        const isOpen = inlineDraft?.kind === kind && inlineDraft.category === category
        return (
          <div className="day-category-row" key={category}>
            <Flex align="center" justify="space-between" gap={12}>
              <span className="day-category-name">{category}</span>
              <Space>
                <strong>{money(totals.get(`${kind}:${category}`) ?? 0)} ₽</strong>
                <Button aria-label={`Добавить: ${category}`} icon={<PlusOutlined />}
                  onClick={() => setInlineDraft(isOpen ? null : emptyDraft(kind, category))} />
              </Space>
            </Flex>
            {isOpen && inlineDraft && (
              <Flex className="day-inline-form" gap={8} wrap>
                <InputNumber autoFocus className="day-amount-input" min={0} precision={2}
                  placeholder="Сумма" value={inlineDraft.amount}
                  onChange={(amount) => setInlineDraft({ ...inlineDraft, amount })} />
                <Input className="day-comment-input" placeholder="Комментарий"
                  value={inlineDraft.comment}
                  onChange={(event) => setInlineDraft({ ...inlineDraft, comment: event.target.value })} />
                <Button type="primary" loading={saving} onClick={() => void saveDraft(inlineDraft)}>
                  Сохранить
                </Button>
              </Flex>
            )}
          </div>
        )
      })}
    </Card>
  )

  const balance = Number(data?.balance ?? 0)
  const mobileCategories = mobileDraft?.kind === 'income' ? INCOME_CATEGORIES : EXPENSE_CATEGORIES

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
          <Tag color={telegramStarted ? 'success' : 'error'}>
            TG: {telegramStarted ? 'работает' : 'не запущен'}
          </Tag>
        </Flex>

        <Card className={`day-total-card ${balance >= 0 ? 'positive' : 'negative'}`}>
          <Typography.Text className="day-total-label">ИТОГ ДНЯ</Typography.Text>
          <div className="day-balance">{balance >= 0 ? '+' : '−'}{money(Math.abs(balance))} ₽</div>
          <Typography.Text type="secondary">
            заработали {money(data?.income_total ?? 0)} ₽ − потратили {money(data?.expense_total ?? 0)} ₽
          </Typography.Text>
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={12}>{categoryCard('income', 'Заработали сегодня', INCOME_CATEGORIES)}</Col>
          <Col xs={24} xl={12}>{categoryCard('expense', 'Потратили сегодня', EXPENSE_CATEGORIES)}</Col>
        </Row>

        <Card className="day-entries-card" title="Записи дня">
          {!data?.entries.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Записей пока нет" /> :
            data.entries.map((entry) => (
              <Flex className="day-entry" key={entry.id} align="center" justify="space-between" gap={12}>
                <div className="day-entry-main">
                  <Space wrap size={6}>
                    <Typography.Text type="secondary">{entry.time}</Typography.Text>
                    <strong>{entry.category}</strong>
                    <Typography.Text className={entry.kind === 'income' ? 'income-value' : 'expense-value'}>
                      {entry.kind === 'income' ? '+' : '−'}{money(entry.amount)} ₽
                    </Typography.Text>
                  </Space>
                  <div className="day-entry-note">
                    {entry.description || 'Без комментария'} · {entry.entered_by}
                  </div>
                </div>
                {entry.can_delete && (
                  <Popconfirm title="Удалить запись?" description="Это действие нельзя отменить."
                    okText="Удалить" cancelText="Нет" onConfirm={() => void removeEntry(entry.id)}>
                    <Button danger aria-label="Удалить запись" icon={<CloseOutlined />} />
                  </Popconfirm>
                )}
              </Flex>
            ))}
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} md={12}><Button className="day-action-button" block onClick={() => onNavigate('leads')}>
            Новые заявки {newLeads} <ArrowRightOutlined />
          </Button></Col>
          <Col xs={24} md={12}><Button className="day-action-button" block onClick={() => onNavigate('finance')}>
            На проверку {reviewCount} <ArrowRightOutlined />
          </Button></Col>
        </Row>
      </div>

      <FloatButton className="day-mobile-float" type="primary" icon={<PlusOutlined />}
        tooltip="Добавить запись" onClick={() => { setMobileDraft(null); setMobileOpen(true) }} />
      <Modal title="Добавить запись" open={mobileOpen} footer={null} onCancel={() => setMobileOpen(false)}>
        {!mobileDraft ? (
          <div className="day-mobile-grid">
            <Button type="primary" onClick={() => setMobileDraft(emptyDraft('income', ''))}>Заработали</Button>
            <Button danger onClick={() => setMobileDraft(emptyDraft('expense', ''))}>Потратили</Button>
          </div>
        ) : !mobileDraft.category ? (
          <div className="day-mobile-grid">
            {mobileCategories.map((category) => <Button key={category}
              onClick={() => setMobileDraft({ ...mobileDraft, category })}>{category}</Button>)}
          </div>
        ) : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Title level={5} style={{ margin: 0 }}>{mobileDraft.category}</Typography.Title>
            <InputNumber autoFocus className="day-mobile-amount" min={0} precision={2}
              placeholder="Сумма" value={mobileDraft.amount}
              onChange={(amount) => setMobileDraft({ ...mobileDraft, amount })} />
            <Input.TextArea rows={3} placeholder="Комментарий" value={mobileDraft.comment}
              onChange={(event) => setMobileDraft({ ...mobileDraft, comment: event.target.value })} />
            <Button block type="primary" loading={saving} onClick={() => void saveDraft(mobileDraft)}>Сохранить</Button>
          </Space>
        )}
      </Modal>
    </Spin>
  )
}
