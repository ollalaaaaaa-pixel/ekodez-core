export type ActionTarget = {
  screen: 'leads' | 'objects' | 'finance' | 'inventory'
  kind: 'lead' | 'object' | 'document' | 'transaction' | 'inventory'
  id: number
  periodId?: number
  periodMonth?: string
}
