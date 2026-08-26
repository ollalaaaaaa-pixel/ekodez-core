import { useEffect, useMemo, useState } from 'react'
import { Card, Col, DatePicker, Empty, List, Row, Spin, Statistic, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import './DashboardPage.css'

const API = 'http://127.0.0.1:8000'
const { RangePicker } = DatePicker

type Daily = { date: string; revenue: string; expenses: string; profit: string }
type Dashboard = {
  revenue: string
  expenses: string
  profit: string
  margin_pct: string
  total_leads: number
  closed_leads: number
  conversion_rate: string
  average_check: string
  best_day: { date: string; revenue: string } | null
  top_objects: { object_id: number; name: string; revenue: string }[]
  top_services: { category: string; revenue: string }[]
  unassigned_revenue: string
  daily: Daily[]
}

const money = (value: string) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(value))

function DailyChart({ rows }: { rows: Daily[] }) {
  if (!rows.length) return <Empty description="Нет операций за выбранный период" />
  const width = 760
  const height = 220
  const padding = 28
  const values = rows.flatMap((row) => [Number(row.revenue), Number(row.profit)])
  const maximum = Math.max(...values.map(Math.abs), 1)
  const x = (index: number) =>
    rows.length === 1 ? width / 2 : padding + (index * (width - 2 * padding)) / (rows.length - 1)
  const y = (value: string) => height / 2 - (Number(value) / maximum) * (height / 2 - padding)
  const points = (field: 'revenue' | 'profit') =>
    rows.map((row, index) => `${x(index)},${y(row[field])}`).join(' ')

  return (
    <div className="dashboard-chart-wrap">
      <svg
        className="dashboard-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="График выручки и прибыли по дням"
      >
        <line x1={padding} y1={height / 2} x2={width - padding} y2={height / 2} className="chart-axis" />
        <polyline points={points('revenue')} className="chart-revenue" />
        <polyline points={points('profit')} className="chart-profit" />
      </svg>
      <div className="chart-legend"><span className="revenue-dot" /> Выручка <span className="profit-dot" /> Прибыль</div>
    </div>
  )
}

export default function DashboardPage() {
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().startOf('month'), dayjs()])
  const [data, setData] = useState<Dashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const query = useMemo(
    () => `start_date=${range[0].format('YYYY-MM-DD')}&end_date=${range[1].format('YYYY-MM-DD')}`,
    [range],
  )

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    fetch(`${API}/api/analytics/dashboard?${query}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Не удалось загрузить дашборд')
        return response.json()
      })
      .then((body) => {
        setData(body)
        setError('')
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
          setError('Не удалось загрузить дашборд')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [query])

  return (
    <Spin spinning={loading}>
      <div className="dashboard-page">
        <div className="dashboard-toolbar">
          <Typography.Title level={3}>Дашборд</Typography.Title>
          <RangePicker
            allowClear={false}
            value={range}
            format="DD.MM.YYYY"
            onChange={(value) => value?.[0] && value[1] && setRange([value[0], value[1]])}
          />
        </div>
        {error ? <Typography.Paragraph type="danger">{error}</Typography.Paragraph> : null}
        <Row gutter={[16, 16]}>
          <Col xs={12} lg={6}><Card><Statistic title="Выручка" value={money(data?.revenue ?? '0')} suffix="₽" /></Card></Col>
          <Col xs={12} lg={6}><Card><Statistic title="Расходы" value={money(data?.expenses ?? '0')} suffix="₽" /></Card></Col>
          <Col xs={12} lg={6}><Card><Statistic title="Прибыль" value={money(data?.profit ?? '0')} suffix="₽" /></Card></Col>
          <Col xs={12} lg={6}><Card><Statistic title="Маржа" value={data?.margin_pct ?? '0.00'} suffix="%" /></Card></Col>
          <Col xs={12} lg={6}><Card><Statistic title="Заявки" value={data?.total_leads ?? 0} /></Card></Col>
          <Col xs={12} lg={6}><Card><Statistic title="Закрытые заявки" value={data?.closed_leads ?? 0} /></Card></Col>
          <Col xs={12} lg={6}><Card><Statistic title="Конверсия" value={data?.conversion_rate ?? '0.00'} suffix="%" /></Card></Col>
          <Col xs={12} lg={6}><Card><Statistic title="Средний чек" value={money(data?.average_check ?? '0')} suffix="₽" /></Card></Col>
        </Row>
        <Card className="dashboard-best-day">
          <Typography.Text type="secondary">Лучший день</Typography.Text>
          <div className="dashboard-best-day-value">
            {data?.best_day
              ? `${dayjs(data.best_day.date).format('DD.MM.YYYY')} · ${money(data.best_day.revenue)} ₽`
              : 'Нет данных'}
          </div>
        </Card>
        <Card className="dashboard-section" title="Выручка и прибыль по дням">
          <DailyChart rows={data?.daily ?? []} />
        </Card>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card className="dashboard-section" title="Топ объектов — по привязанным операциям">
              {!data?.top_objects.length ? (
                <Empty description="Привяжите доходы к объектам в „Финансах“" />
              ) : (
                <List dataSource={data.top_objects} renderItem={(item) => (
                  <List.Item extra={<strong>{money(item.revenue)} ₽</strong>}>{item.name}</List.Item>
                )} />
              )}
              <Typography.Text type="secondary">Не привязано к объектам: {money(data?.unassigned_revenue ?? '0')} ₽</Typography.Text>
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card className="dashboard-section" title="Топ услуг">
              <List dataSource={data?.top_services ?? []} renderItem={(item) => (
                <List.Item extra={<strong>{money(item.revenue)} ₽</strong>}>{item.category}</List.Item>
              )} />
            </Card>
          </Col>
        </Row>
      </div>
    </Spin>
  )
}
