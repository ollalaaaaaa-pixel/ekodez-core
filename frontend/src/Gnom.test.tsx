import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import GnomLeadHints from './GnomLeadHints'
import GnomPage from './GnomPage'

const response = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }))
afterEach(()=>vi.restoreAllMocks())
describe('Gnom workflow',()=>{
  test('repeat banner contains safe history and warranty',async()=>{
    const fetchMock=vi.spyOn(globalThis,'fetch').mockImplementation(()=>response({last_treatment:'2026-08-20T12:00:00',pests:['клопы'],methods:['гель'],price:'2500.00',warranty_until:'2026-09-19'}))
    render(<GnomLeadHints leadId={7} />)
    expect(await screen.findByText('Объект обслуживался')).toBeTruthy()
    expect(screen.getByText(/2500.00/)).toBeTruthy()
    expect(fetchMock.mock.calls[0][0]).toContain('/leads/7/history')
    expect(screen.queryByText('Справочная цена по истории')).toBeNull()
  })
  test('price hint is informational and never sends an update',async()=>{
    const fetchMock=vi.spyOn(globalThis,'fetch').mockImplementation(()=>response({median_price:'3000.00',sample_count:5}))
    const user=userEvent.setup()
    render(<GnomLeadHints />)
    for(const [label,value] of [['Вредитель для справочной цены','клопы'],['Тип площади','Комнаты'],['Город для справочной цены','Архангельск']]) {
      await user.click(screen.getByLabelText(label))
      await user.click(screen.getByTitle(value))
    }
    expect(await screen.findByText(/3000.00 ₽, записей: 5/)).toBeTruthy()
    expect(fetchMock.mock.calls.every(([,init])=>!init?.method || init.method==='GET')).toBe(true)
  })
  test('owner sees masked staging and upload requires explicit confirmation',async()=>{
    const data={settings:{weekly_enabled:false,warranty_days:null},runs:[],expenses:[],candidates:[{id:1,kind:'chemical',preview:'Из истории, требует подтверждения: ***',status:'pending',inventory_id:null}],analytics:{aggregators:[],revenue_by_month:{},average_check:null,lead_time_hours:null,rescheduled:0}}
    const fetchMock=vi.spyOn(globalThis,'fetch').mockImplementation(input=>response(String(input).includes('/overview')?data:[]))
    const user=userEvent.setup()
    render(<GnomPage />)
    expect(await screen.findByText('Из истории, требует подтверждения: ***')).toBeTruthy()
    await user.upload(screen.getByLabelText('Файл истории Гном'),new File(['test'],'test.csv',{type:'text/csv'}))
    await user.click(screen.getByRole('button',{name:'Импортировать файл'}))
    expect((await screen.findAllByText('Импортировать выбранный файл истории?')).length).toBeGreaterThan(0)
    expect(fetchMock.mock.calls.some(([input])=>String(input).includes('/import?'))).toBe(false)
    await user.click(screen.getByRole('button',{name:'Отмена'}))
  })
})
