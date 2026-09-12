import { useEffect, useState } from 'react'
import { Button, Card, Input, Select, Space, Tag, message } from 'antd'
import { API } from './api'

type Category = { id: number; title: string; kind: string; sort_order: number; is_active: boolean }
export default function SettingsPage() {
  const [rows, setRows] = useState<Category[]>([])
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState('expense')
  const [editing, setEditing] = useState<Category | null>(null)
  const [dragged, setDragged] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const load = async () => {
    const response = await fetch(`${API}/api/transaction-categories`)
    if (!response.ok) throw new Error('Не удалось загрузить категории')
    setRows(await response.json())
  }
  useEffect(() => { void load().catch(reason => message.error(String(reason))) }, [])
  const mutate = async (path: string, method: string, payload?: unknown) => {
    setBusy(true)
    try {
      const response = await fetch(`${API}/api/transaction-categories${path}`, {
        method, headers: { 'Content-Type': 'application/json' },
        ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
      })
      if (!response.ok) throw new Error('Изменения не сохранены. Проверьте название и повторите.')
      await load()
      return true
    } catch (reason) { message.error(String(reason)); return false }
    finally { setBusy(false) }
  }
  const save = async () => {
    if (!title.trim()) return
    if (await mutate(editing ? `/${editing.id}` : '', editing ? 'PATCH' : 'POST', {
      title: title.trim(), kind, sort_order: editing?.sort_order ?? rows.length,
    })) { setTitle(''); setEditing(null) }
  }
  const move = async (from: number, to: number) => {
    if (busy || from === to || to < 0 || to >= rows.length) return
    const next = [...rows]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    await mutate('/reorder', 'PATCH', { items: next.map((row, index) => ({ id: row.id, sort_order: index })) })
  }
  return <Card title="Категории операций">
    <Space wrap>
      <Input aria-label="Название категории" value={title} onChange={event => setTitle(event.target.value)} placeholder="Название категории" />
      <Select disabled={!!editing} value={kind} onChange={setKind} options={[{ value: 'income', label: 'Доход' }, { value: 'expense', label: 'Расход' }]} />
      <Button type="primary" loading={busy} onClick={() => void save()}>{editing ? 'Сохранить' : 'Добавить'}</Button>
      {editing && <Button onClick={() => { setEditing(null); setTitle('') }}>Отмена</Button>}
    </Space>
    <p>Перетащите категорию или используйте стрелки. Скрытые категории остаются в истории операций.</p>
    {rows.map((row, index) => <div key={row.id} draggable={!busy}
      onDragStart={() => setDragged(index)} onDragEnd={() => setDragged(null)}
      onDragOver={event => event.preventDefault()}
      onDrop={event => { event.preventDefault(); if (dragged !== null) void move(dragged, index); setDragged(null) }}
      style={{ display: 'flex', gap: 8, alignItems: 'center', padding: 8 }}>
      <Tag color={row.kind === 'income' ? 'green' : 'red'}>{row.kind === 'income' ? 'Доход' : 'Расход'}</Tag>
      <span style={{ flex: 1 }}>{row.title}</span>
      <Button disabled={busy || index === 0} aria-label={`Поднять ${row.title}`} onClick={() => void move(index, index - 1)}>↑</Button>
      <Button disabled={busy || index === rows.length - 1} aria-label={`Опустить ${row.title}`} onClick={() => void move(index, index + 1)}>↓</Button>
      <Button disabled={busy} onClick={() => { setEditing(row); setTitle(row.title); setKind(row.kind) }}>Изменить</Button>
      <Button danger disabled={busy} onClick={() => void mutate(`/${row.id}`, 'DELETE')}>Скрыть</Button>
    </div>)}
  </Card>
}
