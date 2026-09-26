import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Spin, Tag } from 'antd'
import { API } from './api'
import type { ActionTarget } from './actionNavigation'
import './TodayActionPlan.css'

type ActionItem = {
  kind: ActionTarget['kind']
  id: number
  due_date: string | null
  status: string
  urgency: 'overdue' | 'today' | 'attention'
  masked_label: string
  linked_object_due?: boolean
  target: ActionTarget
}
type ActionPlan = {
  date: string
  role: 'owner' | 'master'
  counts: Record<string, number>
  items: ActionItem[]
}
type Props = { onOpen: (target: ActionTarget) => void; onNavigate: (screen: string, kind?: ActionTarget['kind']) => void }

const sections = [
  { kind: 'lead', title: 'Заявки', count: 'lead_overdue', screen: 'leads' },
  { kind: 'object', title: 'Объекты', count: 'object_due', screen: 'objects' },
  { kind: 'document', title: 'Документы', count: 'document_review', screen: 'objects' },
  { kind: 'transaction', title: 'Финансы', count: 'transaction_review', screen: 'finance' },
  { kind: 'inventory', title: 'Склад', count: 'inventory_low', screen: 'inventory' },
] as const
const actionLabels: Record<ActionTarget['kind'], string> = {
  lead: 'заявку', object: 'объект', document: 'документы',
  transaction: 'операцию', inventory: 'препарат',
}
const statusLabels: Record<string, string> = {
  new: 'новая', in_work: 'в работе', active: 'активен', low_stock: 'низкий остаток',
}
const sectionTotal = (section: (typeof sections)[number], counts: Record<string, number>) =>
  section.kind === 'lead'
    ? (counts.lead_overdue ?? 0) + (counts.lead_today ?? 0)
    : (counts[section.count] ?? 0)

export default function TodayActionPlan({ onOpen, onNavigate }: Props) {
  const [plan, setPlan] = useState<ActionPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    setFailed(false)
    try {
      const response = await fetch(`${API}/api/day/action-plan`, { credentials: 'include' })
      if (!response.ok) throw new Error('action plan unavailable')
      const payload: unknown = await response.json()
      if (!payload || typeof payload !== 'object' || !('counts' in payload)
        || !('items' in payload) || !Array.isArray(payload.items)) {
        throw new Error('invalid action plan')
      }
      setPlan(payload as ActionPlan)
    } catch {
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    void load()
    const refresh = window.setInterval(() => { void load() }, 300_000)
    return () => window.clearInterval(refresh)
  }, [load])

  const card = (item: ActionItem) => (
    <div className="today-action" key={`${item.kind}-${item.id}-${item.status}`}>
      <div className="today-action-copy">
        <strong>{item.masked_label}</strong>
        <span>{item.due_date ? `${item.due_date} · ` : ''}{statusLabels[item.status] ?? item.status}</span>
      </div>
      {item.urgency === 'overdue' && <Tag color="red">Просрочено</Tag>}
      {item.linked_object_due && <Tag color="blue">Повторная обработка объекта</Tag>}
      <Button size="small" onClick={() => onOpen(item.target)}
        aria-label={`Открыть ${actionLabels[item.kind]} #${item.id}`}>Открыть</Button>
    </div>
  )

  return <Card className="today-plan" title="План на сегодня">
    {loading && <Spin aria-label="Загрузка плана" />}
    {!loading && failed && <Alert type="warning" title="Не удалось загрузить план"
      action={<Button onClick={() => void load()}>Повторить</Button>} />}
    {!loading && !failed && plan && <>
      <div className="today-plan-counters">
        <span>Просрочено <b>{(plan.counts.lead_overdue ?? 0) + (plan.counts.object_overdue ?? 0)}</b></span>
        <span>На сегодня <b>{(plan.counts.lead_today ?? 0) + (plan.counts.object_today ?? 0)}</b></span>
        {plan.role === 'owner' && <span>Решения <b>{(plan.counts.document_review ?? 0) + (plan.counts.transaction_review ?? 0)}</b></span>}
      </div>
      {plan.items.length === 0 ? <p>Срочных дел нет</p> : <>
        <div className="today-plan-priority">{plan.items.slice(0, 3).map(card)}</div>
        {plan.items.length > 3 && <details className="today-plan-more">
          <summary>Остальные дела ({plan.items.length - 3})</summary>
          {plan.items.slice(3).map(card)}
        </details>}
        <div className="today-plan-sections">
          {sections.filter(section => sectionTotal(section, plan.counts) > 0).map(section =>
            <Button key={section.kind} type="link" onClick={() => onNavigate(section.screen, section.kind)}>
              {section.title}: {sectionTotal(section, plan.counts)} · {sectionTotal(section, plan.counts) > 5 ? 'Все' : 'Перейти в раздел'}
            </Button>)}
        </div>
      </>}
    </>}
  </Card>
}
