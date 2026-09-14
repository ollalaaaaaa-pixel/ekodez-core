import { useEffect, useState } from 'react'
import { API } from './api'
import { INCOME_CATEGORIES } from './dictionaries'

export function useIncomeCategories() {
  const [categories, setCategories] = useState<string[]>([...INCOME_CATEGORIES])
  useEffect(() => {
    const controller = new AbortController()
    void fetch(`${API}/api/transaction-categories?kind=income`, { signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(rows => {
        if (Array.isArray(rows)) setCategories(rows.map((row: { title: string }) => row.title))
      }).catch(() => {})
    return () => controller.abort()
  }, [])
  return categories
}
