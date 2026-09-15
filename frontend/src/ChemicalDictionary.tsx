import { useEffect, useState } from 'react'
import { Alert, Descriptions, Form, Input, Select, Space, Typography } from 'antd'
import { API } from './api'

export const PEST_TAGS = ['клопы', 'тараканы', 'грызуны', 'плесень', 'клещи', 'муравьи'] as const
export type ChemicalNotes = {
  active_substance?: string | null
  resistance_note?: string | null
  alternatives?: number[]
  dosage_note?: string | null
  hazard_class?: string | null
  pest_tags?: string[]
}
type Position = ChemicalNotes & { id: number; chemical_name: string; quantity: string; unit: string }

export function ChemicalDetails({ row, positions = [] }: { row: ChemicalNotes; positions?: Position[] }) {
  return <Descriptions size="small" column={1} items={[
    { key: 'substance', label: 'Действующее вещество', children: row.active_substance || 'Не указано' },
    { key: 'resistance', label: 'Устойчивость', children: row.resistance_note || 'Не указана' },
    { key: 'dosage', label: 'Расход на м² / литр', children: row.dosage_note || 'Не указан' },
    { key: 'hazard', label: 'Класс опасности', children: row.hazard_class || 'Не указан' },
    { key: 'pests', label: 'Вредители', children: row.pest_tags?.join(', ') || 'Не указаны' },
    { key: 'alternatives', label: 'Альтернативы', children: row.alternatives?.map(id => positions.find(item => item.id === id)?.chemical_name || `Позиция #${id}`).join(', ') || 'Не указаны' },
  ]} />
}

export function ChemicalFormFields({ positions, currentId }: { positions: Position[]; currentId?: number }) {
  return <>
    <Form.Item name="active_substance" label="Действующее вещество"><Input maxLength={300} /></Form.Item>
    <Form.Item name="resistance_note" label="Заметка об устойчивости"><Input.TextArea maxLength={5000} /></Form.Item>
    <Form.Item name="dosage_note" label="Расход на м² / литр"><Input.TextArea maxLength={5000} /></Form.Item>
    <Form.Item name="hazard_class" label="Класс опасности"><Input maxLength={100} /></Form.Item>
    <Form.Item name="pest_tags" label="Вредители"><Select mode="multiple" options={PEST_TAGS.map(value => ({ value, label: value }))} /></Form.Item>
    <Form.Item name="alternatives" label="Альтернативные препараты"><Select mode="multiple" optionFilterProp="label" options={positions.filter(row => row.id !== currentId).map(row => ({ value: row.id, label: `${row.chemical_name} (#${row.id})` }))} /></Form.Item>
  </>
}

export function pestForCategory(category: string | null): string | undefined {
  const normalized = category?.trim().toLowerCase()
  if (PEST_TAGS.some(pest => pest === normalized)) return normalized
  return ({ 'дератизация': 'грызуны', 'обработка от клещей': 'клещи' } as Record<string, string>)[normalized || '']
}

export function ChemicalRecommendations({ category }: { category: string | null }) {
  const [selected, setSelected] = useState<string>()
  const pest = selected || pestForCategory(category)
  const [result, setResult] = useState<{ pest: string; rows: Position[]; error?: boolean }>()
  useEffect(() => {
    if (!pest) return
    const controller = new AbortController()
    fetch(`${API}/api/inventory/recommend?${new URLSearchParams({ pest })}`, { credentials: 'include', signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(); return await response.json() as Position[] })
      .then(rows => setResult({ pest, rows }))
      .catch(() => { if (!controller.signal.aborted) setResult({ pest, rows: [], error: true }) })
    return () => controller.abort()
  }, [pest])
  return <Space orientation="vertical" style={{ width: '100%', marginTop: 12 }}>
    <Typography.Text strong>Рекомендованные препараты</Typography.Text>
    <Select aria-label="Вредитель для подбора" placeholder="Уточните вредителя" value={pest} onChange={setSelected} style={{ width: '100%' }} options={PEST_TAGS.map(value => ({ value, label: value }))} />
    {pest && result?.pest !== pest ? <Typography.Text>Загрузка препаратов…</Typography.Text> : null}
    {result?.pest === pest && result?.error ? <Alert type="error" title="Не удалось загрузить препараты" /> : null}
    {result?.pest === pest && !result?.error && result?.rows.length === 0 ? <Typography.Text>Подходящих препаратов в наличии нет</Typography.Text> : null}
    {result?.pest === pest && result?.rows.map(row => <div key={row.id}>
      <Typography.Text strong>{row.chemical_name} — {row.quantity} {row.unit}</Typography.Text>
      <ChemicalDetails row={row} positions={result.rows} />
    </div>)}
    <Typography.Text type="secondary">Подбор по данным владельца. Расход и применение сверяйте с инструкцией препарата.</Typography.Text>
  </Space>
}
