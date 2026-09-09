import { useEffect, useState } from 'react'
import { Card, Table, Typography } from 'antd'
import { API } from './api'

type Metric = { source: string; label: string; leads: number; expenses: string; paid_revenue: string; cpl: string | null; roas: string | null }
type Metrics = { channels: Metric[]; unassigned_ad_expenses: string }

export default function MarketingPanel({ query }: { query: string }) {
  const [data, setData] = useState<Metrics | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API}/api/analytics/marketing?${query}`, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(); return response.json() })
      .then((body: Metrics) => { if (!controller.signal.aborted) setData(body) })
      .catch(() => { if (!controller.signal.aborted) { setData(null); setError('Маркетинговые показатели недоступны. В этой версии просмотр — только с компьютера владельца (localhost).') } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [query])
  return <Card title="Маркетинг: заявки и рекламные расходы" loading={loading} className="dashboard-section">
    {error ? <Typography.Paragraph type="warning">{error}</Typography.Paragraph> : <>
      <Table<Metric> rowKey="source" pagination={false} dataSource={data?.channels ?? []} scroll={{x:720}} columns={[
        {title:'Источник',dataIndex:'label'}, {title:'Заявки',dataIndex:'leads'},
        {title:'Реклама, ₽',dataIndex:'expenses'}, {title:'CPL, ₽',dataIndex:'cpl',render:value=>value ?? '—'},
        {title:'Оплаты, ₽',dataIndex:'paid_revenue'}, {title:'ROAS, ×',dataIndex:'roas',render:value=>value ?? '—'},
      ]} />
      <Typography.Paragraph>Рекламные расходы без источника: {data?.unassigned_ad_expenses ?? '—'} ₽.</Typography.Paragraph>
    </>}
    <Typography.Paragraph type="secondary">Заявки — по дате создания (Москва); расходы и оплаты — по дате операции в выбранном периоде. Оплаты учитываются только по связанным заявкам, в том числе созданным раньше. Переходы в бот не считаются заявками. ROAS — выручка к расходам на рекламу, не прибыль и не ROMI. При отсутствии заявок CPL не рассчитывается.</Typography.Paragraph>
  </Card>
}
