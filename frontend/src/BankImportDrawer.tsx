import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message,
  notification,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { CheckOutlined, FileExcelOutlined, UploadOutlined } from '@ant-design/icons'
import './BankImportDrawer.css'
import { INCOME_CATEGORIES } from './dictionaries'

const API = 'http://127.0.0.1:8000'

type BankPreviewRow = {
  operation_type: string
  operation_date: string
  doc_number: string
  amount: string
  description: string
  payment_purpose: string
  counterparty_name: string
  counterparty_inn: string
  counterparty_inn_masked: string
  source_hash: string
  kind: 'income' | 'expense'
  category: string | null
  channel: string | null
  comment: string
  needs_review: boolean
  is_transfer: boolean
}

type EditableBankRow = BankPreviewRow & {
  categoryOverride?: string
  review_confirmed: boolean
}

type ConfirmResult = {
  imported: number
  skipped_duplicates: number
  batch_id: string
  imported_income_amount: string
  imported_expense_amount: string
  duplicate_income_amount: string
  duplicate_expense_amount: string
  excluded_credit_amount: string
  excluded_debit_amount: string
  statement_credit_total: string
  statement_debit_total: string
  credit_reconciled: boolean
  debit_reconciled: boolean
}

type ExpenseCategory = { id: number; name: string }

type PreviewErrorDetail = {
  message?: string
  found_columns?: string[]
  missing_columns?: string[]
  searched_row?: number | null
}

type Props = {
  open: boolean
  onClose: () => void
  onImported: () => void
}

const money = (value: string) =>
  new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value))

const previewErrorText = (detail: unknown) => {
  if (typeof detail === 'string') return detail
  if (!detail || typeof detail !== 'object') return 'Неизвестная ошибка файла'
  const data = detail as PreviewErrorDetail
  const parts = [data.message ?? 'Не удалось распознать заголовки']
  if (data.searched_row) parts.push(`Строка: ${data.searched_row}`)
  if (data.found_columns?.length) {
    parts.push(`Найдены: ${data.found_columns.join(', ')}`)
  }
  if (data.missing_columns?.length) {
    parts.push(`Отсутствуют: ${data.missing_columns.join(', ')}`)
  }
  return parts.join('. ')
}

export default function BankImportDrawer({ open, onClose, onImported }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [rows, setRows] = useState<EditableBankRow[]>([])
  const [expenseCategories, setExpenseCategories] = useState<string[]>([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [result, setResult] = useState<ConfirmResult | null>(null)
  const [previewError, setPreviewError] = useState('')

  useEffect(() => {
    if (!open) return
    fetch(API + '/api/expense-categories')
      .then((response) => {
        if (!response.ok) throw new Error('Не удалось загрузить статьи расходов')
        return response.json() as Promise<ExpenseCategory[]>
      })
      .then((categories) => setExpenseCategories(categories.map((item) => item.name)))
      .catch(() => message.error('Не удалось загрузить статьи расходов'))
  }, [open])

  const visibleRows = useMemo(() => rows.filter((row) => !row.is_transfer), [rows])
  const excludedCount = rows.length - visibleRows.length
  const reviewRows = rows.filter((row) => row.needs_review)
  const confirmedReviewCount = reviewRows.filter((row) => row.review_confirmed).length
  const hasUnconfirmedReviews = rows.some(
    (row) => row.needs_review && !row.review_confirmed,
  )

  const updateRow = (hash: string, changes: Partial<EditableBankRow>) => {
    setRows((current) =>
      current.map((row) => (row.source_hash === hash ? { ...row, ...changes } : row)),
    )
  }

  const loadPreview = async () => {
    if (!file) {
      message.warning('Сначала выберите XLSX-файл')
      return
    }
    setPreviewLoading(true)
    setResult(null)
    setPreviewError('')
    try {
      const body = new FormData()
      body.append('file', file)
      const response = await fetch(API + '/api/bank/preview', { method: 'POST', body })
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { detail?: unknown }
          | null
        throw new Error(previewErrorText(payload?.detail))
      }
      const previewRows = (await response.json()) as BankPreviewRow[]
      setRows(previewRows.map((row) => ({ ...row, review_confirmed: false })))
      if (!previewRows.length) message.info('В выписке нет операций')
    } catch (error) {
      const detail = error instanceof Error
        ? error.message
        : 'Не удалось прочитать XLSX. Проверьте формат выписки Т-Банка.'
      setPreviewError(detail)
      message.error('Не удалось прочитать выписку')
    } finally {
      setPreviewLoading(false)
    }
  }

  const confirmImport = async () => {
    if (!file || hasUnconfirmedReviews) return
    setConfirmLoading(true)
    try {
      const transactions = rows.map((row) => ({
        operation_type: row.operation_type,
        operation_date: row.operation_date,
        doc_number: row.doc_number,
        amount: row.amount,
        description: row.description,
        payment_purpose: row.payment_purpose,
        counterparty_name: row.counterparty_name,
        counterparty_inn: row.counterparty_inn,
        source_hash: row.source_hash,
        category_override: row.categoryOverride ?? null,
        review_confirmed: row.review_confirmed,
      }))
      const response = await fetch(API + '/api/bank/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_filename: file.name, transactions }),
      })
      if (!response.ok) throw new Error('Сервер отклонил подтверждение')
      const confirmed = (await response.json()) as ConfirmResult
      setResult(confirmed)
      notification.success({
        message: `Импортировано ${confirmed.imported} записей`,
        description: `Пропущено дублей: ${confirmed.skipped_duplicates}`,
      })
      onImported()
    } catch {
      message.error('Импорт не выполнен. Проверьте отмеченные строки и повторите.')
    } finally {
      setConfirmLoading(false)
    }
  }

  const closeDrawer = () => {
    setFile(null)
    setRows([])
    setResult(null)
    setPreviewError('')
    onClose()
  }

  const columns: TableColumnsType<EditableBankRow> = [
    { title: 'Дата', dataIndex: 'operation_date', width: 105 },
    {
      title: 'Контрагент',
      width: 220,
      render: (_, row) => (
        <div>
          <div>{row.counterparty_name || '—'}</div>
          {row.counterparty_inn_masked ? (
            <Typography.Text type="secondary">
              ИНН {row.counterparty_inn_masked}
            </Typography.Text>
          ) : null}
        </div>
      ),
    },
    {
      title: 'Сумма',
      width: 130,
      render: (_, row) => (
        <strong className={row.kind === 'income' ? 'bank-income' : 'bank-expense'}>
          {row.kind === 'income' ? '+' : '−'}{money(row.amount)} ₽
        </strong>
      ),
    },
    {
      title: 'Категория',
      width: 230,
      render: (_, row) =>
        row.needs_review ? (
          <Select
            aria-label={`Категория операции ${row.doc_number}`}
            className="bank-category-select"
            placeholder="Выберите статью"
            value={row.categoryOverride}
            options={(row.kind === 'income' ? INCOME_CATEGORIES : expenseCategories).map(
              (category) => ({ label: category, value: category }),
            )}
            onChange={(categoryOverride) =>
              updateRow(row.source_hash, { categoryOverride, review_confirmed: false })
            }
          />
        ) : (
          row.category ?? '—'
        ),
    },
    {
      title: 'Канал',
      width: 120,
      render: (_, row) => (row.kind === 'income' ? row.channel ?? 'Не указан' : '—'),
    },
    { title: 'Комментарий', dataIndex: 'comment', width: 260 },
    {
      title: 'Проверка',
      width: 180,
      render: (_, row) => {
        if (!row.needs_review) return <Tag color="green">Определено</Tag>
        if (row.review_confirmed) {
          return <Tag icon={<CheckOutlined />} color="green">Выбор подтверждён</Tag>
        }
        return (
          <Button
            className="bank-review-button"
            disabled={!row.categoryOverride}
            onClick={() => updateRow(row.source_hash, { review_confirmed: true })}
          >
            Подтвердить выбор
          </Button>
        )
      },
    },
  ]

  return (
    <Drawer
      className="bank-import-drawer"
      title="Импорт выписки Т-Банка"
      open={open}
      width="min(1100px, 100vw)"
      onClose={closeDrawer}
      extra={<Button onClick={closeDrawer}>Закрыть</Button>}
    >
      <Space direction="vertical" size="large" className="bank-import-content">
        <Card size="small">
          <Flex gap={12} wrap align="center">
            <Upload
              accept=".xlsx"
              maxCount={1}
              showUploadList={false}
              beforeUpload={(nextFile) => {
                setFile(nextFile)
                setRows([])
                setResult(null)
                setPreviewError('')
                return false
              }}
            >
              <Button icon={<UploadOutlined />} className="bank-touch-button">
                Выбрать XLSX
              </Button>
            </Upload>
            <Typography.Text>
              {file ? file.name : 'Файл не выбран'}
            </Typography.Text>
            <Button
              type="primary"
              icon={<FileExcelOutlined />}
              loading={previewLoading}
              disabled={!file}
              onClick={loadPreview}
              className="bank-touch-button"
            >
              Проверить выписку
            </Button>
          </Flex>
        </Card>

        {previewError ? (
          <Alert
            type="error"
            showIcon
            message="Ошибка предпросмотра"
            description={previewError}
          />
        ) : null}

        {rows.length ? (
          <>
            {excludedCount ? (
              <Alert
                type="info"
                showIcon
                message={`Отсечено переводов/возвратов: ${excludedCount}`}
                description="Эти строки участвуют в сверке оборотов банка, но не сохраняются как доходы или расходы."
              />
            ) : null}
            {hasUnconfirmedReviews ? (
              <Alert
                type="warning"
                showIcon
                message="Есть операции, требующие проверки"
                description="Выберите статью и явно подтвердите выбор в каждой жёлтой строке."
              />
            ) : null}
            <Table<EditableBankRow>
              rowKey="source_hash"
              columns={columns}
              dataSource={visibleRows}
              pagination={{ pageSize: 15 }}
              scroll={{ x: 1245 }}
              rowClassName={(row) => (row.needs_review ? 'bank-import-review-row' : '')}
              locale={{ emptyText: <Empty description="Все строки отсечены правилами" /> }}
            />
            <div className="bank-confirm-panel">
              <Flex justify="space-between" gap={8} wrap>
                <Typography.Text strong>
                  Спорные строки: {confirmedReviewCount} из {reviewRows.length} подтверждены
                </Typography.Text>
                <Typography.Text type={hasUnconfirmedReviews ? 'warning' : 'success'}>
                  {hasUnconfirmedReviews
                    ? 'Кнопка заблокирована: подтвердите все спорные строки.'
                    : 'Все спорные строки подтверждены — импорт доступен.'}
                </Typography.Text>
              </Flex>
              <Button
                type="primary"
                size="large"
                block
                loading={confirmLoading}
                disabled={
                  !visibleRows.length || hasUnconfirmedReviews || Boolean(result)
                }
                onClick={confirmImport}
                className="bank-confirm-button"
              >
                Подтвердить и сохранить
              </Button>
            </div>
          </>
        ) : null}

        {result ? (
          <Card title="Отчёт импорта" className="bank-import-report">
            <Descriptions bordered column={{ xs: 1, sm: 2 }} size="small">
              <Descriptions.Item label="Импортировано записей">
                {result.imported}
              </Descriptions.Item>
              <Descriptions.Item label="Пропущено дублей">
                {result.skipped_duplicates}
              </Descriptions.Item>
              <Descriptions.Item label="Импортировано доходов">
                {money(result.imported_income_amount)} ₽
              </Descriptions.Item>
              <Descriptions.Item label="Импортировано расходов">
                {money(result.imported_expense_amount)} ₽
              </Descriptions.Item>
              <Descriptions.Item label="Дубли доходов">
                {money(result.duplicate_income_amount)} ₽
              </Descriptions.Item>
              <Descriptions.Item label="Дубли расходов">
                {money(result.duplicate_expense_amount)} ₽
              </Descriptions.Item>
              <Descriptions.Item label="Отсечено переводов/возвратов — кредит">
                {money(result.excluded_credit_amount)} ₽
              </Descriptions.Item>
              <Descriptions.Item label="Отсечено переводов/возвратов — дебет">
                {money(result.excluded_debit_amount)} ₽
              </Descriptions.Item>
              <Descriptions.Item label="Оборот банка — кредит">
                {money(result.statement_credit_total)} ₽{' '}
                <Tag color={result.credit_reconciled ? 'green' : 'red'}>
                  {result.credit_reconciled ? 'Сошлось' : 'Не сошлось'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Оборот банка — дебет">
                {money(result.statement_debit_total)} ₽{' '}
                <Tag color={result.debit_reconciled ? 'green' : 'red'}>
                  {result.debit_reconciled ? 'Сошлось' : 'Не сошлось'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        ) : null}
      </Space>
    </Drawer>
  )
}
