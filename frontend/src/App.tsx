import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowDown, ArrowLeft, ArrowRight, Check, CheckCheck, ChevronRight, CircleHelp, Copy, Headphones, House, Info, LayoutGrid, LoaderCircle, Package, RefreshCw, Search, ShieldCheck, ShoppingBag, Smartphone, Sparkles, X } from 'lucide-react'
import { api, ApiError, errorText, mediaUrl } from './api'
import type { Me, Order, Product, ProductSummary, Quote, Shop } from './types'

const rub = (value: number) => new Intl.NumberFormat('ru-RU').format(value)
const available = (p: {availability: string; quantity: number | null}) => p.availability !== 'out' && p.quantity !== 0
const statusLabel = (p: {availability: string}) => ({in_stock: 'В наличии', preorder: 'Под заказ', out: 'Нет в наличии'}[p.availability])

type Store = { shop: Shop; me: Me | null; authError: string; quote: Quote | null; setQuote: (value: Quote | null) => void }
const StoreContext = createContext<Store>(null!)
const useStore = () => useContext(StoreContext)
const emptyShop: Shop = { name: 'CHINA PHONE', about: '', admin_username: null, brands: [], popular_ids: [] }

function useLoad<T>(fetcher: () => Promise<T>, dependencies: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setData(null)
    fetcher().then(value => { if (active) setData(value) }).catch(e => { if (active) setError(errorText(e)) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
    // Every caller passes stable primitives for the data it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, reload])
  return { data, error, loading, retry: () => setReload(x => x + 1) }
}

function Busy() { return <div className="loading" role="status"><LoaderCircle className="spin" size={26} /><span>Загружаем магазин</span></div> }
function ErrorBox({text, retry}: {text: string; retry?: () => void}) {
  return <div className="error-box" role="alert"><CircleHelp size={22} /><p>{text}</p>{retry && <button onClick={retry} className="text-button"><RefreshCw size={16} /> Повторить</button>}</div>
}
function SectionTitle({eyebrow, title, children}: {eyebrow?: string; title: string; children?: ReactNode}) {
  return <div className="section-title"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2></div>{children}</div>
}
function Empty({filtered = false, reset}: {filtered?: boolean; reset?: () => void}) {
  return <div className="empty-state"><div className="empty-art"><ShoppingBag size={38} strokeWidth={1.4} /><span><Sparkles size={15} /></span></div>
    <h3>{filtered ? 'Пока ничего не нашли' : 'Хорошие вещи скоро здесь'}</h3>
    <p>{filtered ? 'Попробуйте другое название или уберите фильтры.' : 'Каталог пока пуст. Скоро здесь появятся товары. А пока можно узнать больше о магазине.'}</p>
    {reset ? <button className="secondary" onClick={reset}>Сбросить фильтры <ArrowRight size={16} /></button> : <Link className="text-button" to="/about">О магазине <ArrowRight size={16} /></Link>}
  </div>
}
function PhoneArt() {
  return <div className="phone-art" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" />
    <div className="illustration-phone phone-back"><div className="camera-island"><i /><i /><i /><b /></div><span className="phone-mark">C / P</span></div>
    <div className="illustration-phone phone-front"><div className="island" /><div className="phone-sphere" /><div className="phone-line" /><span>MAKE IT YOURS.</span></div>
    <span className="floating-spark"><Sparkles size={19} /></span></div>
}

function ProductImage({url, name, className = ''}: {url?: string | null; name: string; className?: string}) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [url])
  return url && !failed ? <img className={className} src={mediaUrl(url)} alt={name} loading="lazy" onError={() => setFailed(true)} /> : <div className={'image-placeholder ' + className}><Smartphone size={48} strokeWidth={1} /><span>Фото скоро появится</span></div>
}
function ProductTile({p}: {p: ProductSummary}) {
  return <Link className="product-tile" to={'/product/' + p.id}><div className="tile-image"><ProductImage url={p.image} name={p.name} /><span className={'stock-tag ' + (p.availability === 'in_stock' ? 'is-green' : '')}>{statusLabel(p)}</span></div>
    <div className="tile-copy"><span className="product-brand">{p.brand}</span><h3>{p.name}</h3><p>{p.short_description}</p><div className="tile-price"><strong>{p.min_price !== p.max_price && <small>от </small>}{rub(p.min_price)} <small>сом</small></strong><span><ArrowRight size={17} /></span></div></div></Link>
}
function Pager({page, total, change}: {page: number; total: number; change: (page: number) => void}) {
  if (total <= 5) return null
  return <div className="pager"><button aria-label="Предыдущая страница" disabled={!page} onClick={() => change(page - 1)}><ArrowLeft size={18} /></button><span>{page + 1} / {Math.ceil(total / 5)}</span><button aria-label="Следующая страница" disabled={(page + 1) * 5 >= total} onClick={() => change(page + 1)}><ArrowRight size={18} /></button></div>
}

function SearchBar({value, change, submit}: {value: string; change: (v: string) => void; submit: () => void}) {
  return <form className="search-bar" role="search" onSubmit={e => { e.preventDefault(); submit() }}><Search size={21} /><input aria-label="Поиск смартфона" value={value} onChange={e => change(e.target.value)} placeholder="Найти свой смартфон" maxLength={100} /><button aria-label="Искать" type="submit"><ArrowRight size={18} /></button></form>
}

function HomePage() {
  const {shop, authError} = useStore()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const products = useLoad(() => api.products('page=0&sort=popular'))
  return <>
    <div className="welcome"><span className="eyebrow">ТЕХНОЛОГИИ БЛИЖЕ</span><h1>Найди свой <span>следующий.</span></h1><p>Смартфоны из Китая. С вниманием к деталям.</p></div>
    <SearchBar value={search} change={setSearch} submit={() => navigate('/catalog?query=' + encodeURIComponent(search))} />
    <section className="hero"><div className="hero-copy"><span className="hero-badge"><span /> ВЫБИРАЙ ПО-СВОЕМУ</span><h2>Больше<br />возможностей.<br /><em>Твой выбор.</em></h2><p>Нужный цвет. Твоя память.<br />Всё в одном месте.</p><Link className="hero-cta" to="/catalog">Смотреть каталог <ArrowRight size={17} /></Link></div><PhoneArt /></section>
    <div className="trust-strip"><span><ShieldCheck size={18} /> Личная консультация</span><i /><span><Package size={18} /> Оформление без оплаты</span></div>
    <SectionTitle eyebrow="ЛЕГКО НАЙТИ" title="С чего начнём?" />
    <div className="category-scroll"><Link to="/catalog" className="category active"><Smartphone size={22} /><span>Все смартфоны</span><ArrowRight size={15} /></Link><Link to="/catalog?available=true" className="category"><CheckCheck size={22} /><span>В наличии</span></Link>{shop.brands.map(b => <Link key={b} className="category brand-category" to={'/catalog?brand=' + encodeURIComponent(b)}>{b}</Link>)}</div>
    <SectionTitle eyebrow="ПОДБЕРИ ПОД СЕБЯ" title={shop.popular_ids.length ? 'Популярный выбор' : 'В центре внимания'}><Link className="all-link" to="/catalog">Все <ArrowRight size={16} /></Link></SectionTitle>
    {authError ? <ErrorBox text={authError} /> : products.loading ? <Busy /> : products.error ? <ErrorBox text={products.error} retry={products.retry} /> : products.data?.items.length ? <div className="product-grid">{products.data.items.map(p => <ProductTile key={p.id} p={p} />)}</div> : <Empty />}
    <Link to="/contact" className="consultation"><span className="consult-icon"><Headphones size={26} /></span><div><h3>Поможем с выбором</h3><p>Спросите о модели, комплектации и доставке</p></div><ArrowRight size={21} /></Link>
    <p className="quiet-footer">CHINA PHONE <span>·</span> Технологии, которые подходят тебе</p>
  </>
}

function CatalogPage() {
  const {shop, authError} = useStore()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('query') || '')
  const [minimum, setMinimum] = useState(params.get('minimum') || '')
  const [maximum, setMaximum] = useState(params.get('maximum') || '')
  const [filterError, setFilterError] = useState('')
  const query = new URLSearchParams(params); query.delete('search')
  const load = useLoad(() => api.products(query.toString()), [query.toString()])
  const update = (key: string, value: string) => { const p = new URLSearchParams(params); p.delete('page'); if (value) p.set(key, value); else p.delete(key); setParams(p) }
  useEffect(() => { setSearch(params.get('query') || ''); setMinimum(params.get('minimum') || ''); setMaximum(params.get('maximum') || '') }, [params])
  return <><div className="page-heading"><span className="eyebrow">ТВОЯ НОВАЯ ТЕХНИКА</span><h1>Каталог</h1><p>Выбирай то, что подходит именно тебе.</p></div>
    <SearchBar value={search} change={setSearch} submit={() => update('query', search.trim())} />
    <div className="filter-chips"><button className={!params.get('brand') ? 'selected' : ''} onClick={() => update('brand', '')}>Все бренды</button>{shop.brands.map(b => <button key={b} className={params.get('brand') === b ? 'selected' : ''} onClick={() => update('brand', b)}>{b}</button>)}</div>
    <details className="filters"><summary><span>Цена и наличие</span><span className="filter-count">{params.get('available') || params.get('minimum') || params.get('maximum') ? 'Применены' : 'Настроить'} <ArrowDown size={14} /></span></summary><form onSubmit={e => {e.preventDefault(); if ((minimum && !/^\d+$/.test(minimum)) || (maximum && !/^\d+$/.test(maximum)) || (minimum && +minimum < 1) || (maximum && +maximum < 1) || (+minimum > +(maximum || 1000000000))) {setFilterError('Укажите корректный диапазон цены в целых сомах.'); return} setFilterError(''); const p = new URLSearchParams(params); p.delete('page'); for (const [k,v] of [['minimum',minimum],['maximum',maximum]]) v ? p.set(k,v) : p.delete(k); setParams(p)}}>
      <div className="price-range"><label>От, сом<input inputMode="numeric" value={minimum} onChange={e => setMinimum(e.target.value)} placeholder="Любая" maxLength={10} /></label><span>—</span><label>До, сом<input inputMode="numeric" value={maximum} onChange={e => setMaximum(e.target.value)} placeholder="Любая" maxLength={10} /></label></div>
      <label className="checkbox"><input type="checkbox" checked={params.get('available') === 'true'} onChange={e => update('available', e.target.checked ? 'true' : '')} />Только в наличии</label>{filterError && <p className="inline-error">{filterError}</p>}<button className="secondary" type="submit">Применить цену <Check size={16} /></button></form></details>
    <div className="result-header"><span>{load.data ? `Найдено: ${load.data.total}` : 'Подбираем модели'}</span>{query.size > 0 && <button className="text-button" onClick={() => setParams({})}>Сбросить <X size={15} /></button>}</div>
    {authError ? <ErrorBox text={authError} /> : load.loading ? <Busy /> : load.error ? <ErrorBox text={load.error} retry={load.retry} /> : load.data?.items.length ? <><div className="product-grid">{load.data.items.map(p => <ProductTile key={p.id} p={p} />)}</div><Pager page={load.data.page} total={load.data.total} change={p => update('page', String(p))} /></> : <Empty filtered={query.size > 0} reset={query.size > 0 ? () => setParams({}) : undefined} />}
  </>
}

function ProductPage() {
  const {id = ''} = useParams()
  const {setQuote, authError} = useStore()
  const navigate = useNavigate()
  const load = useLoad(() => api.product(id), [id])
  const [color, setColor] = useState(''), [memory, setMemory] = useState(''), [image, setImage] = useState(0)
  const [price, setPrice] = useState<number | null>(null), [priceBusy, setPriceBusy] = useState(false)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const key = useRef(crypto.randomUUID())
  const priceRequest = useRef(0)
  useEffect(() => { if (load.data) {setColor(load.data.colors[0] || ''); setMemory(load.data.memories[0] || ''); setImage(0); setError(''); key.current = crypto.randomUUID()} }, [load.data])
  useEffect(() => {key.current = crypto.randomUUID(); setPrice(null); if (!load.data || !color || !memory || !available(load.data)) return; const controller = new AbortController(); const serial = ++priceRequest.current; setPriceBusy(true); setError(''); api.price(load.data, color, memory, controller.signal).then(r => {if (serial === priceRequest.current) setPrice(r.price)}).catch(e => {if (!controller.signal.aborted) setError(errorText(e))}).finally(() => {if (!controller.signal.aborted) setPriceBusy(false)}); return () => {priceRequest.current++; controller.abort()} }, [color,memory,load.data])
  async function review(p: Product) { if (busy || price === null) return; setBusy(true); setError(''); try {const q = await api.quote(p,color,memory,key.current); setQuote(q); window.Telegram?.WebApp.HapticFeedback?.impactOccurred('light'); navigate('/checkout')} catch(e) {setError(errorText(e))} finally {setBusy(false)} }
  if (load.loading) return <Busy />
  if (authError || load.error || !load.data) return <ErrorBox text={authError || load.error} retry={load.retry} />
  const p = load.data
  return <><Link className="back-link" to="/catalog"><ArrowLeft size={17} /> Каталог</Link><div className="product-gallery"><ProductImage className="detail-image" url={p.images[image]} name={p.name} /><span className={'stock-tag ' + (p.availability === 'in_stock' ? 'is-green' : '')}>{statusLabel(p)}</span>{p.images.length > 1 && <div className="image-dots">{p.images.map((_,i) => <button key={i} className={i === image ? 'selected' : ''} onClick={() => setImage(i)} aria-label={'Фото ' + (i+1)} />)}</div>}</div>
    <div className="product-heading"><span className="eyebrow">{p.brand} · {p.model}</span><h1>{p.name}</h1><span className="product-id">Артикул CP-{p.id}</span></div>
    <div className="price-line"><strong>{priceBusy ? 'Уточняем цену…' : rub(price ?? (p.variants.length ? Math.min(...p.variants.map(v => v.price)) : p.price))} <small>{!priceBusy && 'сом'}</small></strong><span>KGS</span></div>
    <div className="option-section"><div className="option-label">Цвет <strong>{color}</strong></div><div className="options">{p.colors.map(c => <button disabled={busy} key={c} className={c === color ? 'selected' : ''} onClick={() => setColor(c)}>{c === color && <Check size={14} />}{c}</button>)}</div></div>
    <div className="option-section"><div className="option-label">Память <strong>{memory}</strong></div><div className="options">{p.memories.map(m => <button disabled={busy} key={m} className={m === memory ? 'selected' : ''} onClick={() => setMemory(m)}>{m}</button>)}</div></div>
    {error && <ErrorBox text={error} retry={load.retry} />}<button className="primary wide" disabled={busy || priceBusy || price === null || !available(p)} onClick={() => review(p)}>{busy ? <LoaderCircle className="spin" size={18} /> : <ShoppingBag size={18} />}{available(p) ? 'Оформить заказ' : 'Нет в наличии'}<ArrowRight size={18} /></button><p className="under-button">Проверьте все детали перед подтверждением</p>
    <div className="detail-section"><h2>О смартфоне</h2><p>{p.description}</p></div><div className="detail-section"><h2>Характеристики</h2><p>{p.specs}</p><div className="spec-row"><span>Наличие</span><strong>{statusLabel(p)}</strong></div>{p.quantity !== null && <div className="spec-row"><span>На складе</span><strong>{p.quantity} шт.</strong></div>}</div>
    <Link className="mini-help" to="/contact"><Headphones size={20} /><span>Остались вопросы? Напишите продавцу</span><ChevronRight size={17} /></Link>
  </>
}

function CheckoutPage() {
  const {quote, setQuote} = useStore()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const inFlight = useRef(false)
  async function confirm() { if (!quote || inFlight.current) return; inFlight.current = true; setBusy(true); setError(''); try {const result = await api.confirm(quote.token); setQuote(null); window.Telegram?.WebApp.HapticFeedback?.notificationOccurred('success'); navigate('/success/' + result.order.id, {replace: true})} catch(e) {setError(errorText(e) + (e instanceof ApiError && e.status === 409 ? '' : ' При повторном подтверждении второй заказ не создастся.'))} finally {inFlight.current = false; setBusy(false)} }
  if (!quote) return <><div className="page-heading"><span className="eyebrow">ПОЧТИ ТВОЙ</span><h1>Оформление</h1></div><Empty /><Link className="primary wide" to="/catalog">Выбрать смартфон <ArrowRight size={18} /></Link></>
  return <><div className="page-heading"><span className="eyebrow">ОСТАЛСЯ ОДИН ШАГ</span><h1>Всё верно?</h1><p>Проверьте свой выбор перед отправкой продавцу.</p></div><div className="checkout-summary"><div className="summary-icon"><Smartphone size={32} /></div><span className="eyebrow">ТВОЙ ВЫБОР</span><h2>{quote.product_name}</h2><p>Артикул CP-{quote.product_id}</p><div className="spec-row"><span>Цвет</span><strong>{quote.color}</strong></div><div className="spec-row"><span>Память</span><strong>{quote.memory}</strong></div><div className="summary-total"><span>Итого</span><strong>{rub(quote.price)} <small>сом</small></strong></div></div>
    <div className="notice"><ShieldCheck size={22} /><p>Заказ передадим продавцу. Наличие, комплектацию и доставку согласуете лично. Оплата в приложении не требуется.</p></div>{error && <ErrorBox text={error} />}
    <button className="primary wide" onClick={confirm} disabled={busy}>{busy ? <LoaderCircle className="spin" size={18} /> : <Check size={18} />}{busy ? 'Сохраняем заказ…' : 'Подтвердить заказ'}</button><button className="text-button cancel-checkout" disabled={busy} onClick={() => {setQuote(null); navigate('/product/' + quote.product_id)}}>Изменить выбор</button>
  </>
}

function SellerButton({message}: {message?: string}) {
  const {shop} = useStore()
  if (!shop.admin_username) return <p className="muted">Прямая связь пока не настроена. Сохранённые заказы передаются продавцу через бота.</p>
  const url = 'https://t.me/' + shop.admin_username + (message ? '?text=' + encodeURIComponent(message) : '')
  return <a className="primary wide" href={url} target="_blank" rel="noreferrer" onClick={e => {const tg = window.Telegram?.WebApp; if (tg?.initData) {e.preventDefault(); tg.openTelegramLink(url)}}}><Headphones size={18} />Написать продавцу <ArrowRight size={18} /></a>
}
function OrderView({o}: {o: Order}) {
  const [copied, setCopied] = useState(false), [copyError, setCopyError] = useState(false)
  return <><div className="order-detail"><span className={'order-status status-' + o.status}>{o.status_label}</span><h2>{o.number}</h2><p>{new Date(o.created_at).toLocaleString('ru-RU')}</p><div className="order-product"><Smartphone size={28} /><div><h3>{o.product_name}</h3><span>{o.color} · {o.memory}</span></div></div><div className="summary-total"><span>Сумма заказа</span><strong>{rub(o.price)} <small>сом</small></strong></div></div>
    {!o.admin_notified && <div className="notice"><Info size={20} /><p>Заказ сохранён, ожидает подтверждения продавца. Уведомление будет доставлено повторно.</p></div>}
    <div className="message-box"><h3>Готовое сообщение продавцу</h3><pre>{o.message}</pre><button className="secondary wide" onClick={async () => {try {await navigator.clipboard.writeText(o.message); setCopied(true); setCopyError(false)} catch {setCopyError(true)}}}>{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? 'Скопировано' : 'Скопировать заказ'}</button>{copyError && <p className="muted">Выделите текст сообщения выше и скопируйте вручную.</p>}</div><SellerButton message={o.message} />
  </>
}
function SuccessPage() {
  const {id = ''} = useParams()
  const load = useLoad(() => api.order(id), [id])
  if (load.loading) return <Busy />
  if (load.error || !load.data) return <ErrorBox text={load.error} retry={load.retry} />
  return <><div className="success-heading"><span><Check size={32} /></span><span className="eyebrow">ОТЛИЧНЫЙ ВЫБОР</span><h1>Заказ сохранён</h1><p>Он уже в вашей истории.<br />Продавец подтвердит детали и наличие.</p></div><OrderView o={load.data} /><Link to="/orders" className="text-button center-link">Все мои заказы <ArrowRight size={16} /></Link></>
}
function OrdersPage() {
  const [page, setPage] = useState(0)
  const {authError} = useStore()
  const load = useLoad(() => api.orders(page), [page])
  return <><div className="page-heading"><span className="eyebrow">ВСЁ ПОД КОНТРОЛЕМ</span><h1>Мои заказы</h1><p>Ваша история и актуальные статусы.</p></div><button className="text-button refresh-orders" onClick={load.retry}><RefreshCw size={15} /> Обновить статусы</button>
    {authError ? <ErrorBox text={authError} /> : load.loading ? <Busy /> : load.error ? <ErrorBox text={load.error} retry={load.retry} /> : !load.data?.items.length ? <div className="empty-state"><div className="empty-art"><Package size={38} /></div><h3>Здесь будет ваш первый заказ</h3><p>Выберите смартфон в каталоге — мы сохраним все детали здесь.</p><Link className="primary" to="/catalog">Открыть каталог <ArrowRight size={16} /></Link></div> : <><div className="order-list">{load.data.items.map(o => <Link key={o.id} to={'/order/' + o.id} className="order-tile"><div className="order-top"><span>{o.number}</span><span className={'order-status status-' + o.status}>{o.status_label}</span></div><h3>{o.product_name}</h3><p>{o.color} · {o.memory}</p><div className="order-bottom"><strong>{rub(o.price)} сом</strong><ChevronRight size={18} /></div></Link>)}</div><Pager page={load.data.page} total={load.data.total} change={setPage} /></>}
  </>
}
function OrderPage() {
  const {id = ''} = useParams()
  const load = useLoad(() => api.order(id), [id])
  return <><Link className="back-link" to="/orders"><ArrowLeft size={16} /> Все заказы</Link>{load.loading ? <Busy /> : load.error || !load.data ? <ErrorBox text={load.error} retry={load.retry} /> : <OrderView o={load.data} />}</>
}
function AboutPage() {
  const {shop, authError} = useStore()
  return <><div className="page-heading"><span className="eyebrow">ПРИЯТНО ПОЗНАКОМИТЬСЯ</span><h1>Техника ближе.<br /><span>Выбор проще.</span></h1></div><div className="about-banner"><Smartphone size={42} strokeWidth={1.1} /><h2>{shop.name}</h2><span>СМАРТФОНЫ ИЗ КИТАЯ</span></div>{authError && <ErrorBox text={authError} />}<div className="detail-section"><h2>О магазине</h2><p>{shop.about || 'Информация появится после подключения к магазину через Telegram.'}</p></div><div className="steps"><div><span>01</span><h3>Выберите своё</h3><p>Найдите модель, цвет и объём памяти.</p></div><div><span>02</span><h3>Проверьте детали</h3><p>Актуальная цена появится до подтверждения.</p></div><div><span>03</span><h3>Договоритесь лично</h3><p>Продавец уточнит наличие, доставку и условия.</p></div></div><SellerButton /></>
}
function ContactPage() {
  return <><div className="page-heading"><span className="eyebrow">МЫ РЯДОМ</span><h1>Давайте<br />поговорим.</h1><p>Поможем разобраться в моделях и деталях заказа.</p></div><div className="contact-art"><Headphones size={65} strokeWidth={1.1} /><span className="online-mark"><span /> Личная консультация</span></div><div className="detail-section"><h2>Спросите продавца</h2><p>Наличие и комплектация, особенности модели, сроки и условия доставки — обсудим в личном чате Telegram.</p></div><SellerButton /><div className="notice"><Package size={21} /><p>Уже оформили заказ? Его номер, статус и готовое сообщение находятся в разделе «Мои заказы».</p></div><Link className="secondary wide" to="/orders">Мои заказы <ArrowRight size={17} /></Link></>
}

function TelegramBridge() {
  const {pathname} = useLocation()
  const navigate = useNavigate()
  useEffect(() => {const tg = window.Telegram?.WebApp; if (!tg) return; const apply = () => {document.documentElement.dataset.theme = tg.colorScheme; document.documentElement.style.setProperty('--tg-top', (tg.contentSafeAreaInset?.top || 0) + 'px'); document.documentElement.style.setProperty('--tg-bottom', (tg.safeAreaInset?.bottom || 0) + 'px')}; tg.ready(); tg.expand(); apply(); tg.onEvent('themeChanged',apply); tg.onEvent('safeAreaChanged',apply); return () => {tg.offEvent('themeChanged',apply); tg.offEvent('safeAreaChanged',apply)}}, [])
  useEffect(() => {window.scrollTo({top:0}); const tg = window.Telegram?.WebApp; if (!tg) return; const back = () => navigate('/catalog'); pathname === '/' ? tg.BackButton.hide() : tg.BackButton.show(); tg.BackButton.onClick(back); return () => tg.BackButton.offClick(back)}, [pathname,navigate])
  return null
}

export default function App() {
  const [shop,setShop] = useState<Shop>(emptyShop), [me,setMe] = useState<Me | null>(null), [authError,setAuthError] = useState(''), [quote,setQuoteState] = useState<Quote | null>(null)
  useEffect(() => {let active = true; Promise.all([api.shop(),api.me()]).then(([s,u]) => {if (!active) return; setShop(s);setMe(u); try {const saved = sessionStorage.getItem('cp-checkout-' + u.id); if (saved) {const q = JSON.parse(saved) as Quote; if (/^[a-f0-9]{16}$/.test(q.token) && q.expires_at > Date.now()/1000) setQuoteState(q)}} catch {/* Storage is optional in Telegram clients. */}}).catch(e => {if (active) setAuthError(errorText(e))}); return () => {active = false}}, [])
  const setQuote = (q: Quote | null) => {setQuoteState(q); if (me) {try {q ? sessionStorage.setItem('cp-checkout-' + me.id,JSON.stringify(q)) : sessionStorage.removeItem('cp-checkout-' + me.id)} catch {/* Keep checkout usable without browser storage. */}}}
  return <StoreContext.Provider value={{shop,me,authError,quote,setQuote}}><TelegramBridge /><div className="app-shell"><header className="topbar"><Link to="/" className="brand"><span className="brand-mark"><Smartphone size={22} /></span><span><strong>{shop.name}</strong><small>ТВОЯ ТЕХНИКА. ТВОЙ ВЫБОР.</small></span></Link><Link to="/about" className="currency">KGS <span>сом</span><ChevronRight size={12} /></Link></header><main><Routes><Route path="/" element={<HomePage />} /><Route path="/catalog" element={<CatalogPage />} /><Route path="/product/:id" element={<ProductPage />} /><Route path="/checkout" element={<CheckoutPage />} /><Route path="/success/:id" element={<SuccessPage />} /><Route path="/orders" element={<OrdersPage />} /><Route path="/order/:id" element={<OrderPage />} /><Route path="/about" element={<AboutPage />} /><Route path="/contact" element={<ContactPage />} /><Route path="*" element={<><Empty /><Link to="/" className="primary">На главную</Link></>} /></Routes></main></div><nav className="bottom-nav" aria-label="Основная навигация"><NavLink end to="/"><House size={21} /><span>Главная</span></NavLink><NavLink to="/catalog"><LayoutGrid size={21} /><span>Каталог</span></NavLink><NavLink to="/checkout" className="cart-nav"><span className="nav-icon"><ShoppingBag size={21} />{quote && <b>1</b>}</span><span>Выбор</span></NavLink><NavLink to="/orders"><Package size={21} /><span>Заказы</span></NavLink><NavLink to="/contact"><Headphones size={21} /><span>Связь</span></NavLink></nav></StoreContext.Provider>
}
