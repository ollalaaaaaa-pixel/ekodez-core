import { useState } from 'react'
import { Layout, Menu, Typography, Card } from 'antd'
import {
  DollarOutlined,
  FileTextOutlined,
  TeamOutlined,
  RobotOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import FinancePage from './FinancePage'
import LeadsPage from './LeadsPage'

const { Header, Sider, Content } = Layout
const { Title } = Typography

const screens: Record<string, string> = {
  finance: 'Финансы',
  leads: 'Заявки',
  clients: 'Клиенты',
  agents: 'Агенты',
  settings: 'Настройки',
}

export default function App() {
  const [current, setCurrent] = useState('finance')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider breakpoint="lg" collapsedWidth="64">
        <div style={{ height: 48, margin: 16, color: '#fff', fontWeight: 700, textAlign: 'center' }}>
          ЭКОДЕЗ
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[current]}
          onClick={(e) => setCurrent(e.key)}
          items={[
            { key: 'finance', icon: <DollarOutlined />, label: 'Финансы' },
            { key: 'leads', icon: <FileTextOutlined />, label: 'Заявки' },
            { key: 'clients', icon: <TeamOutlined />, label: 'Клиенты' },
            { key: 'agents', icon: <RobotOutlined />, label: 'Агенты' },
            { key: 'settings', icon: <SettingOutlined />, label: 'Настройки' },
          ]}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px' }}>
          <Title level={4} style={{ lineHeight: '64px', margin: 0 }}>
            Ekodez Core - {screens[current]}
          </Title>
        </Header>
        <Content style={{ margin: 24 }}>
          {current === 'finance' ? (
            <FinancePage />
          ) : current === 'leads' ? (
            <LeadsPage />
          ) : (
            <Card>
              <p>Экран "{screens[current]}" готовится. Данные появятся после подключения модуля.</p>
            </Card>
          )}
        </Content>
      </Layout>
    </Layout>
  )
}
