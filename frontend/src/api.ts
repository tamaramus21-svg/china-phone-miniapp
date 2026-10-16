import type { Order, Page, Product, ProductSummary, Quote, Shop, Me } from './types'

const origin = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/$/, '')
if (origin && !/^https:\/\/[^/?#]+$/.test(origin)) throw new Error('VITE_API_ORIGIN must be an HTTPS origin')
export const mediaUrl = (path: string) => origin + path
export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }

export async function request<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(25000)
  const response = await fetch(origin + '/api' + path, {
    method: body ? 'POST' : 'GET', signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    headers: { Authorization: 'tma ' + (window.Telegram?.WebApp.initData || ''), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, data.error || 'Не удалось загрузить данные. Попробуйте ещё раз.')
  return data as T
}
export const api = {
  me: () => request<Me>('/me'), shop: () => request<Shop>('/shop'),
  products: (query: string, signal?: AbortSignal) => request<Page<ProductSummary>>('/products?' + query, undefined, signal),
  product: (id: string) => request<Product>('/products/' + id),
  price: (p: Product, color: string, memory: string, signal?: AbortSignal) => request<{price: number}>('/products/' + p.id + '/price', {color, memory, revision: p.revision}, signal),
  quote: (p: Product, color: string, memory: string, request_key: string) => request<Quote>('/quotes', {product_id: p.id, revision: p.revision, color, memory, request_key}),
  confirm: (token: string) => request<{order: Order}>('/orders', {quote_token: token}),
  orders: (page: number) => request<Page<Order>>('/orders?page=' + page),
  order: (id: string) => request<Order>('/orders/' + id),
}
export function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Не удалось связаться с магазином. Проверьте интернет и повторите запрос.'
}
