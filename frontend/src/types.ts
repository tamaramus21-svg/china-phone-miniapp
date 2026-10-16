export interface ProductSummary {
  id: number; name: string; brand: string; model: string; short_description: string
  availability: 'in_stock' | 'preorder' | 'out'; quantity: number | null
  revision: number; min_price: number; max_price: number; image: string | null
}
export interface Product extends Omit<ProductSummary, 'min_price' | 'max_price' | 'image'> {
  price: number; description: string; specs: string; colors: string[]; memories: string[]
  images: string[]; variants: { color: string; memory: string; price: number }[]
}
export interface Quote {
  token: string; product_id: number; product_name: string; revision: number
  color: string; memory: string; price: number; expires_at: number
}
export interface Order {
  id: number; number: string; product_id: number; product_name: string; color: string; memory: string
  price: number; created_at: string; status: string; status_label: string; admin_notified: number; message: string
}
export interface Page<T> { items: T[]; page: number; page_size: number; total: number }
export interface Shop {
  name: string; about: string; admin_username: string | null; brands: string[]; popular_ids: number[]
}
export interface Me { id: number; first_name: string; is_admin: boolean }

interface TelegramApp {
  initData: string; colorScheme: 'light' | 'dark'; version: string
  ready(): void; expand(): void; close(): void
  onEvent(name: string, handler: () => void): void; offEvent(name: string, handler: () => void): void
  openTelegramLink(url: string): void
  BackButton: { show(): void; hide(): void; onClick(fn: () => void): void; offClick(fn: () => void): void }
  HapticFeedback?: { impactOccurred(style: 'light' | 'medium'): void; notificationOccurred(type: 'success' | 'error'): void }
  safeAreaInset?: { top: number; bottom: number }
  contentSafeAreaInset?: { top: number; bottom: number }
}
declare global { interface Window { Telegram?: { WebApp: TelegramApp } } }
