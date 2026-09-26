import { useEffect, useRef, useState } from 'react'
import { Alert, Badge, Button, Layout, Menu, Typography, Card, Spin, message } from 'antd'
import {
  CalendarOutlined,
  DollarOutlined,
  DashboardOutlined,
  FileTextOutlined,
  EnvironmentOutlined,
  ExperimentOutlined,
  TeamOutlined,
  SettingOutlined,
  NotificationOutlined,
  BarChartOutlined,
} from '@ant-design/icons'
import DayPage from './DayPage'
import FinancePage from './FinancePage'
import LeadsPage from './LeadsPage'
import ObjectsPage from './ObjectsPage'
import InventoryPage from './InventoryPage'
import GnomPage from './GnomPage'
import DashboardPage from './DashboardPage'
import ClientsPage from './ClientsPage'
import SettingsPage from './SettingsPage'
import AdsPage from './AdsPage'
import type { AuthSession } from './auth'
import type { ActionTarget } from './actionNavigation'
import { API } from './api'
import { authenticateTelegramMiniApp, getAuthSession, telegramMiniAppInitData } from './auth'

const { Header, Sider, Content } = Layout
const { Title } = Typography

const screens: Record<string, string> = {
  day: 'День',
  leads: 'Заявки',
  objects: 'Объекты',
  inventory: 'Склад',
  finance: 'Финансы',
  dashboard: 'Дашборд',
  clients: 'Клиенты',
  settings: 'Настройки',
  ads: 'Реклама',
  gnom: 'История Гном',
}

export default function App() {
  const [current, setCurrent] = useState('day')
  const [target, setTarget] = useState<ActionTarget | null>(null)
  const [planGroup, setPlanGroup] = useState<{ kind: ActionTarget['kind']; ids: number[] } | null>(null)
  const [mobileLayout, setMobileLayout] = useState(() => window.innerWidth < 992)
  const [menuCollapsed, setMenuCollapsed] = useState(() => window.innerWidth < 992)
  const initData = telegramMiniAppInitData()
  const [authState, setAuthState] = useState<'checking' | 'ready' | 'error'>('checking')
  const [authError, setAuthError] = useState('')
  const [role, setRole] = useState<AuthSession['role'] | null>(null)
  const [unreadAds, setUnreadAds] = useState(0)
  const authStarted = useRef(false)
  const navigate = (screen: string, kind?: ActionTarget['kind']) => {
    if (!kind) { setTarget(null); setPlanGroup(null); setCurrent(screen); return }
    if (role !== 'owner' && (kind === 'document' || kind === 'transaction')) return
    void fetch(`${API}/api/day/action-plan?all=true`, { credentials: 'include' })
      .then(async response => {
        if (!response.ok) throw new Error('action plan unavailable')
        const payload = await response.json() as { group_ids?: Record<string, number[]> }
        const ids = payload.group_ids?.[kind]
        if (!Array.isArray(ids)) throw new Error('invalid action plan')
        setTarget(null)
        setPlanGroup({ kind, ids })
        setCurrent(screen)
      })
      .catch(() => message.error('Не удалось открыть список дел. Повторите попытку.'))
  }
  const openAction = (next: ActionTarget) => {
    if (role !== 'owner' && (next.kind === 'document' || next.kind === 'transaction')) return
    setTarget(next)
    setPlanGroup(null)
    setCurrent(next.screen)
  }

  useEffect(() => {
    if (authStarted.current) return
    authStarted.current = true
    if (initData) window.Telegram?.WebApp?.ready?.()
    const authentication = initData
      ? authenticateTelegramMiniApp(initData)
      : getAuthSession().then((session) => ({ role: session.role }))
    authentication
      .then((session) => {
        setRole(session.role)
        setAuthState('ready')
      })
      .catch((error: unknown) => {
        setAuthError(error instanceof Error ? error.message : 'Не удалось войти через Telegram')
        setAuthState('error')
      })
  }, [initData])

  useEffect(() => {
    if (role !== 'owner') return
    fetch('/api/ads/notifications/unread-count', { credentials: 'include' })
      .then((response) => response.ok ? response.json() : { count: 0 })
      .then((body: { count: number }) => setUnreadAds(body.count))
      .catch(() => setUnreadAds(0))
  }, [role])

  if (authState === 'checking') {
    return <div className="auth-state"><Spin size="large" tip="Вход через Telegram…" /></div>
  }
  if (authState === 'error') {
    return <div className="auth-state"><Alert type="error" showIcon message="Не удалось войти" description={authError} /></div>
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        breakpoint="lg"
        collapsedWidth="0"
        collapsed={menuCollapsed}
        onCollapse={setMenuCollapsed}
        onBreakpoint={(broken) => {
          setMobileLayout(broken)
          if (broken) setMenuCollapsed(true)
        }}
      >
        <div className="app-logo">ЭКОДЕЗ</div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[current]}
          onClick={(e) => {
            navigate(e.key)
            if (mobileLayout) setMenuCollapsed(true)
          }}
          items={[
            { key: 'day', icon: <CalendarOutlined />, label: 'День' },
            { key: 'leads', icon: <FileTextOutlined />, label: 'Заявки' },
            { key: 'objects', icon: <EnvironmentOutlined />, label: 'Объекты' },
            { key: 'inventory', icon: <ExperimentOutlined />, label: 'Склад' },
            { key: 'finance', icon: <DollarOutlined />, label: 'Финансы' },
            { key: 'dashboard', icon: <DashboardOutlined />, label: 'Дашборд' },
            { key: 'clients', icon: <TeamOutlined />, label: 'Клиенты' },
            { key: 'settings', icon: <SettingOutlined />, label: 'Настройки' },
            ...(role === 'owner'
              ? [
                  { key: 'ads', icon: <BarChartOutlined />, label: 'Реклама' },
                  { key: 'gnom', icon: <FileTextOutlined />, label: 'История Гном' },
                ]
              : []),
          ]}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <Title level={4} className="app-title">
            Ekodez Core — {screens[current]}
          </Title>
          {role === 'owner' ? (
            <Badge count={unreadAds}>
              <Button aria-label="Уведомления рекламы" icon={<NotificationOutlined />} onClick={() => navigate('ads')} />
            </Badge>
          ) : null}
        </Header>
        <Content className="app-content">
          {current === 'day' ? (
            <DayPage onNavigate={navigate} onOpen={openAction} />
          ) : current === 'finance' ? (
            <FinancePage targetId={target?.screen === 'finance' ? target.id : undefined}
              planIds={planGroup?.kind === 'transaction' ? planGroup.ids : undefined} />
          ) : current === 'leads' ? (
            <LeadsPage targetId={target?.screen === 'leads' ? target.id : undefined}
              planIds={planGroup?.kind === 'lead' ? planGroup.ids : undefined} />
          ) : current === 'objects' ? (
            <ObjectsPage targetId={target?.screen === 'objects' ? target.id : undefined}
              periodId={target?.kind === 'document' ? target.periodId : undefined}
              periodMonth={target?.kind === 'document' ? target.periodMonth : undefined}
              planIds={planGroup?.kind === 'object' || planGroup?.kind === 'document' ? planGroup.ids : undefined} />
          ) : current === 'inventory' ? (
            <InventoryPage targetId={target?.screen === 'inventory' ? target.id : undefined}
              planIds={planGroup?.kind === 'inventory' ? planGroup.ids : undefined} />
          ) : current === 'dashboard' ? (
            <DashboardPage />
          ) : current === 'clients' ? (
            <ClientsPage />
          ) : current === 'settings' ? (
            <SettingsPage />
          ) : current === 'ads' && role === 'owner' ? (
            <AdsPage onNotificationsRead={() => setUnreadAds(0)} />
          ) : current === 'gnom' && role === 'owner' ? (
            <GnomPage />
          ) : (
            <Card>
              <p>Экран «{screens[current]}» готовится. Данные появятся после подключения модуля.</p>
            </Card>
          )}
        </Content>
      </Layout>
    </Layout>
  )
}
