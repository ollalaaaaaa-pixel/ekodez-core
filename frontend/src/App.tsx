import { useState } from 'react'
import { Layout, Menu, Typography, Card } from 'antd'
import {
  CalendarOutlined,
  DollarOutlined,
  FileTextOutlined,
  TeamOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import DayPage from './DayPage'
import FinancePage from './FinancePage'
import LeadsPage from './LeadsPage'

const { Header, Sider, Content } = Layout
const { Title } = Typography

const screens: Record<string, string> = {
  day: 'День',
  leads: 'Заявки',
  finance: 'Финансы',
  clients: 'Клиенты',
  settings: 'Настройки',
}

export default function App() {
  const [current, setCurrent] = useState('day')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider breakpoint="lg" collapsedWidth="0">
        <div className="app-logo">ЭКОДЕЗ</div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[current]}
          onClick={(e) => setCurrent(e.key)}
          items={[
            { key: 'day', icon: <CalendarOutlined />, label: 'День' },
            { key: 'leads', icon: <FileTextOutlined />, label: 'Заявки' },
            { key: 'finance', icon: <DollarOutlined />, label: 'Финансы' },
            { key: 'clients', icon: <TeamOutlined />, label: 'Клиенты' },
            { key: 'settings', icon: <SettingOutlined />, label: 'Настройки' },
          ]}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <Title level={4} className="app-title">
            Ekodez Core — {screens[current]}
          </Title>
        </Header>
        <Content className="app-content">
          {current === 'day' ? (
            <DayPage onNavigate={setCurrent} />
          ) : current === 'finance' ? (
            <FinancePage />
          ) : current === 'leads' ? (
            <LeadsPage />
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
