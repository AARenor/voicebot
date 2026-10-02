async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  let mode = 'loaded';
  let releaseBooking;
  let turns = 0;
  const requests = [];
  const services = [{id:1,name:'Klassikaline massaaž',duration:60},{id:2,name:'Näohooldus',duration:45},{id:3,name:'Lõõgastav kehahooldus',duration:90}];
  await page.unroute('**/api/**');
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push(url.pathname);
    const reply = (body, status = 200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(body),headers:{'Cache-Control':'no-store'}});
    if (url.pathname === '/api/status') return reply({capabilities:{text_turn_ready:true},telephone:{media_credentials_configured:true,public_ingress_verified:false,carrier_call_verified:false}});
    if (request.headers().authorization !== 'Bearer fixture-operator') return reply({},403);
    if (url.pathname === '/api/calls') return reply({calls:[{at:'2026-10-02 14:32:18',lang:'et',outcome:'tools_ok',source:'demo'},{at:'2026-10-02 14:18:07',lang:'et',outcome:'ok',source:'demo'}]});
    if (url.pathname === '/api/catalogue') return reply({services,providers:[{id:1,name:'Demo teenindaja',services:[1,2,3]}]});
    if (url.pathname === '/api/bookings') {
      if (mode === 'delayed') await new Promise(resolve => releaseBooking = resolve);
      if (mode === 'failure') return reply({},503);
      const date = url.searchParams.get('date');
      const second = url.searchParams.get('page') === '2';
      const selected = second ? services.slice(0,1) : services;
      return reply({items:mode === 'empty' ? [] : selected.map((service,i)=>({id:second?201:i+101,service_name:service.name,provider_name:'Demo teenindaja',start_local:`${date} ${10+i*2}:00:00`,end_local:`${date} ${11+i*2}:00:00`,timezone:'Europe/Tallinn',time_state:'valid',status:'Booked'})),fetched_at:'2026-10-02T14:34:00+03:00',has_more:mode === 'empty'||second?false:'unknown'});
    }
    if (url.pathname === '/api/demo/session') return reply({session_id:'fixture-session',greeting:'Tere! Olen Meretuule Demo Spa virtuaalne abiline. Millist teenust soovid proovida?'});
    if (url.pathname.startsWith('/api/demo/session/')) return reply({ok:true});
    if (url.pathname === '/api/turn') {
      turns++;
      const input = request.postDataJSON();
      return reply({text_heard:input.text,reply:'Klassikaline massaaž kestab 60 minutit. Mis päeval soovid tulla?',outcome:'ok',audio_b64:'',turn_count:turns,expires_in_s:590,booking_changes:[]});
    }
    return reply({},404);
  });
  await page.setViewportSize({width:1440,height:1000});
  const linkFailures = [];
  for (const [query, wantedPage, wantedDate] of [
    ['?page=1.5',1,null], ['?page=Infinity',1,null],
    ['?page=abc',1,null], ['?page=-4',1,null], ['?page=101',1,null],
    ['?date=2026-99-99',1,null], ['?date=2026-02-30',1,null],
    ['?page=2&date=2026-10-09',2,'2026-10-09'],
  ]) {
    await page.goto('http://127.0.0.1:8765/' + query);
    const actual = await page.evaluate(()=>({page:state.page,date:document.getElementById('booking-date').value,today:tallinnDay()}));
    if (actual.page !== wantedPage || actual.date !== (wantedDate || actual.today)) linkFailures.push({query,...actual});
  }
  assert(linkFailures.length===0,`invalid booking links reached the UI: ${JSON.stringify(linkFailures)}`);
  await page.goto('http://127.0.0.1:8765/');
  await page.evaluate(()=>document.fonts.ready);
  assert(requests.every(path=>path==='/api/status'),'signed-out page requested private data');
  await page.screenshot({path:'output/playwright/after-desktop.png',fullPage:true});
  await page.keyboard.press('Tab');
  assert(await page.locator('.skip').evaluate(el=>el===document.activeElement),'skip link is not first keyboard target');
  await page.keyboard.press('Enter');
  assert(await page.locator('#main').evaluate(el=>el===document.activeElement),'skip link did not focus main');
  await page.locator('#booking-auth-link').click();
  assert(await page.locator('#token').evaluate(el=>el===document.activeElement),'connect shortcut did not focus token');
  await page.locator('#token').fill('wrong-fixture-token');
  await page.locator('#connect').click();
  await page.waitForFunction(()=>document.getElementById('auth-status').classList.contains('error'));
  await page.locator('#token').fill('fixture-operator');
  await page.locator('#connect').click();
  await page.waitForFunction(()=>document.querySelectorAll('#bookings tbody tr').length===3);
  assert(await page.locator('#token-field').isHidden(),'credential field remained visible');
  assert(await page.locator('#token').inputValue()==='','credential was not cleared');
  assert(await page.locator('#catalogue li').count()===3,'catalogue did not render');
  assert(await page.locator('#calls li').count()===2,'call journal did not render');
  assert((await page.locator('#bookings tbody tr').first().locator('td').nth(2).textContent()).includes('10:00 – 11:00'),'local booking times did not format');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'output/playwright/after-connected-desktop.png',fullPage:true});
  await page.locator('#booking-next').click();
  await page.waitForFunction(()=>document.querySelector('#bookings tbody tr')?.dataset.bookingId==='201');
  assert(new URL(page.url()).searchParams.get('page')==='2','pagination was not reflected in URL');
  await page.locator('#booking-prev').click();
  await page.waitForFunction(()=>document.querySelectorAll('#bookings tbody tr').length===3);
  mode='failure';
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.getElementById('booking-status').classList.contains('stale'));
  assert(await page.locator('#bookings tbody tr').count()===3,'provider error removed stale rows');
  mode='empty';
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>!document.getElementById('booking-empty').hidden);
  assert(await page.locator('#bookings').isHidden(),'empty schedule displayed an empty table');
  mode='loaded';
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.querySelectorAll('#bookings tbody tr').length===3);
  await page.locator('#demo-start').click();
  await page.waitForFunction(()=>!document.getElementById('demo-text').disabled);
  await page.locator('#demo-text').fill('Kui kaua massaaž kestab?');
  await page.locator('#demo-send').click();
  await page.waitForFunction(()=>document.querySelectorAll('#demo-messages li').length===3);
  assert(await page.locator('#demo-messages .user-message').count()===1,'user bubble missing');
  await page.screenshot({path:'output/playwright/after-conversation-desktop.png',fullPage:true});
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>document.getElementById('demo-status').classList.contains('error'));
  assert((await page.locator('#demo-status').textContent()).includes('Mikrofon'),'microphone denial did not give guidance');
  await page.locator('.navigation a[href="#calls-section"]').click();
  await page.waitForFunction(()=>document.querySelector('.navigation [aria-current]')?.getAttribute('href')==='#calls-section');
  const layouts = [];
  for (const width of [1440,1024,768,700,390,320]) {
    await page.setViewportSize({width,height:900});
    const size = await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert(size.scroll<=size.width,`horizontal overflow at ${width}px: ${size.scroll}`);
    layouts.push(size);
  }
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'output/playwright/after-connected-mobile.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});
  assert(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior)==='auto','reduced motion ignored');
  mode='delayed';
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.getElementById('booking-section').getAttribute('aria-busy')==='true');
  await page.locator('#logout').click();
  releaseBooking();
  await page.waitForFunction(()=>document.getElementById('connection-label').textContent==='Ühendamata');
  assert(await page.locator('#bookings tbody tr').count()===0,'logout retained private rows');
  assert(await page.locator('#demo-messages li').count()===0,'logout retained conversation');
  assert(await page.locator('#catalogue li').count()===0,'logout retained catalogue');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'output/playwright/after-mobile.png',fullPage:true});
  let stalledSignIns = 0;
  await page.route('**/api/calls', async () => { stalledSignIns++; await new Promise(()=>{}); });
  // Exercise real fetch abort without spending 30 seconds on a virtual outage.
  await page.evaluate(()=>{const original=window.setTimeout;window.setTimeout=(fn,delay,...args)=>original(fn,delay===30000?50:delay,...args);});
  await page.locator('#token').fill('fixture-operator');
  await page.locator('#connect').click();
  await page.waitForFunction(()=>document.getElementById('auth-status').textContent.includes('ooteaeg'));
  assert(await page.locator('#connect').isEnabled(),'stalled sign-in left the UI locked');
  assert(await page.locator('#token').inputValue()==='','stalled sign-in retained credential');
  assert(stalledSignIns===1,'stalled sign-in retried automatically');
  assert(errors.length===0,`browser errors: ${errors.join('; ')}`);
  return {result:'passed',layouts,turns,errors,screenshots:5};
}
