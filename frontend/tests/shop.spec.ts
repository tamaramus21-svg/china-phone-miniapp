import { test, expect, type Page } from '@playwright/test'

const product = {id:1,name:'Тестовый смартфон',brand:'ТестБренд',model:'ТестМодель',short_description:'Данные для проверки интерфейса',description:'Тестовое описание',specs:'Тестовые характеристики',price:10000,min_price:10000,max_price:13000,colors:['Чёрный','Белый'],memories:['128 ГБ','256 ГБ'],variants:[{color:'Чёрный',memory:'128 ГБ',price:10000},{color:'Белый',memory:'256 ГБ',price:13000}],availability:'in_stock',quantity:3,revision:1,images:[],image:null}
const quote = {token:'0123456789abcdef',product_id:1,product_name:product.name,revision:1,color:'Белый',memory:'256 ГБ',price:13000,expires_at:Date.now()/1000+3600}
const order = {id:1,number:'CP-TEST0001',product_id:1,product_name:product.name,color:'Белый',memory:'256 ГБ',price:13000,created_at:'2026-10-15T12:00:00+00:00',status:'new',status_label:'Новый',admin_notified:0,message:'Здравствуйте! Хочу заказать тестовый смартфон. Номер заказа CP-TEST0001.'}

async function setup(page: Page, options: {empty?: boolean; dark?: boolean; failedConfirm?: boolean; stale?: boolean} = {}) {
  await page.addInitScript(({dark}) => {
    Object.defineProperty(window,'Telegram',{value:{WebApp:{initData:'synthetic-offline-init-data',colorScheme:dark?'dark':'light',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{hide(){},show(){},onClick(){},offClick(){}},HapticFeedback:{impactOccurred(){},notificationOccurred(){}}}}})
  }, {dark:options.dark})
  await page.route('https://telegram.org/js/telegram-web-app.js',r => r.fulfill({body:'',contentType:'application/javascript'}))
  let confirmations = 0
  const bodies: Record<string,unknown>[] = []
  await page.route('**/api/**',async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    let data: unknown = {}, status = 200
    if (path === '/api/me') data = {id:12345,first_name:'Тест',is_admin:false}
    else if (path === '/api/shop') data = {name:'CHINA PHONE',about:'Информация магазина',admin_username:null,brands:options.empty?[]:['ТестБренд'],popular_ids:[]}
    else if (path === '/api/products') data = {items:options.empty?[]:[product],page:0,page_size:5,total:options.empty?0:1}
    else if (path === '/api/products/1') data = product
    else if (path === '/api/products/1/price') {const body = request.postDataJSON(); data={price:body.color==='Белый' && body.memory==='256 ГБ'?13000:10000}}
    else if (path === '/api/quotes') {bodies.push(request.postDataJSON()); data=quote; if(options.stale){status=409;data={error:'Товар изменился. Обновите карточку.'}}}
    else if (path === '/api/orders' && request.method()==='POST') {confirmations++;bodies.push(request.postDataJSON());data={order,created:true}; if(options.failedConfirm && confirmations===1){status=503;data={error:'Сервис временно недоступен.'}}}
    else if (path === '/api/orders') data={items:[order],page:0,total:1,page_size:5}
    else if (path === '/api/orders/1') data=order
    else {status=404;data={error:'Не найдено'}}
    await route.fulfill({status,body:JSON.stringify(data),contentType:'application/json'})
  })
  return {bodies, confirmations:()=>confirmations}
}

test('empty storefront is responsive and has functional navigation',async({page})=>{
  await setup(page,{empty:true})
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'Хорошие вещи скоро здесь'})).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.screenshot({path:'test-results/home-light.png',fullPage:true})
  await page.getByRole('navigation').getByRole('link',{name:'Каталог'}).click()
  await expect(page.getByRole('heading',{name:'Каталог',exact:true})).toBeVisible()
  await page.getByRole('searchbox').count().catch(()=>0)
  await page.getByLabel('Поиск смартфона').fill('Новая модель')
  await page.getByRole('button',{name:'Искать',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Пока ничего не нашли'})).toBeVisible()
  await page.getByRole('navigation').getByRole('link',{name:'Связь'}).click()
  await expect(page.getByText('Прямая связь пока не настроена.',{exact:false})).toBeVisible()
})

test('dark theme has no horizontal overflow at 320px',async({page})=>{
  await page.setViewportSize({width:320,height:740})
  await setup(page,{empty:true,dark:true})
  await page.goto('/')
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark')
  await expect(page.getByRole('heading',{name:'Хорошие вещи скоро здесь'})).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.screenshot({path:'test-results/home-dark.png',fullPage:true})
})

test('variant checkout uses server quote and preserves it on retry',async({page})=>{
  const state=await setup(page,{failedConfirm:true})
  await page.goto('/#/product/1')
  await page.getByRole('button',{name:'Белый',exact:true}).click()
  await page.getByRole('button',{name:'256 ГБ',exact:true}).click()
  await expect(page.locator('.price-line')).toContainText('13 000')
  await page.getByRole('button',{name:'Оформить заказ'}).click()
  await expect(page.getByRole('heading',{name:'Всё верно?'})).toBeVisible()
  await page.getByRole('button',{name:'Подтвердить заказ'}).click()
  await expect(page.getByRole('alert')).toContainText('второй заказ не создастся')
  await page.reload()
  await expect(page.getByRole('heading',{name:'Всё верно?'})).toBeVisible()
  await page.getByRole('button',{name:'Подтвердить заказ'}).click()
  await expect(page.getByRole('heading',{name:'Заказ сохранён'})).toBeVisible()
  await expect(page.getByText('CP-TEST0001',{exact:true})).toBeVisible()
  expect(state.confirmations()).toBe(2)
  expect(state.bodies.filter(b=>'quote_token' in b)).toEqual([{quote_token:quote.token},{quote_token:quote.token}])
  expect(state.bodies.every(b=>!('price' in b)&&!('user_id' in b))).toBe(true)
  await page.getByRole('navigation').getByRole('link',{name:'Заказы'}).click()
  await expect(page.getByRole('heading',{name:'Мои заказы'})).toBeVisible()
})

test('stale product prevents checkout and offers refresh',async({page})=>{
  await setup(page,{stale:true})
  await page.goto('/#/product/1')
  await page.getByRole('button',{name:'Оформить заказ'}).click()
  await expect(page.getByRole('alert')).toContainText('Товар изменился')
  await expect(page.getByRole('button',{name:'Подтвердить заказ'})).toHaveCount(0)
})

test('outside Telegram authorization error is actionable',async({page})=>{
  await page.route('https://telegram.org/js/telegram-web-app.js',r=>r.fulfill({body:'',contentType:'application/javascript'}))
  await page.route('**/api/**',r=>r.fulfill({status:401,contentType:'application/json',body:JSON.stringify({error:'Откройте магазин через кнопку в Telegram.'})}))
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Откройте магазин через кнопку в Telegram')
  await expect(page.getByRole('heading',{name:'Найди свой следующий.'})).toBeVisible()
})
