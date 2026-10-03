async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  let mode = 'loaded';
  let releaseBooking;
  let turns = 0;
  let speechFails = false;
  const audioUploads = [];
  const requests = [];
  const services = [{id:1,name:'Klassikaline massaaž',duration:60},{id:2,name:'Näohooldus',duration:45},{id:3,name:'Lõõgastav kehahooldus',duration:90}];
  const telephoneCall={id:'a'.repeat(32),channel:'telephone',language:'et',status:'ended',outcome:'booking_confirmed',started_at:'2026-10-03T05:45:00Z',updated_at:'2026-10-03T05:46:22Z',ended_at:'2026-10-03T05:46:22Z',duration_s:82,turns:4,recognized_turns:4,typed_turns:0,empty_turns:0,stt_errors:0,tts_errors:0,provider_errors:0,vad_events:4,needs_attention:false,data_mode:'synthetic',bookings:[{id:'101',action:'confirmed',date:'2026-10-09',start_local:'2026-10-09 10:00:00',timezone:'Europe/Tallinn'}]};
  const browserCall={...telephoneCall,id:'b'.repeat(32),channel:'browser',outcome:'fallback',turns:2,recognized_turns:0,typed_turns:1,stt_errors:1,vad_events:0,needs_attention:true,bookings:[]};
  const stayReceipt={id:'stay_'+'d'.repeat(32),kind:'stay',action:'confirmed',date:'2026-10-12',checkout:'2026-10-14',start_local:'',timezone:'Europe/Tallinn'};
  let historyMode='loaded', releaseHistory;
  await page.unroute('**/api/**');
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push(url.pathname);
    const reply = (body, status = 200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(body),headers:{'Cache-Control':'no-store'}});
    if (url.pathname === '/api/status') return reply({models:{stt:{model:"whisper-large-v3"},llm:{model:"openai/gpt-oss-120b"},tts:{voice:"et-EE-AnuNeural"}},wired:{stt:true,llm_primary:true,tts:true},capabilities:{text_turn_ready:true,booking_read_ready:true},telephone:{media_credentials_configured:true,public_ingress_verified:false,carrier_call_verified:false}});
    if (request.headers().authorization !== 'Bearer fixture-operator') return reply({},403);
    if (url.pathname === '/api/calls') return reply({calls:[{at:'2026-10-02 14:32:18',lang:'et',outcome:'tools_ok',source:'demo'},{at:'2026-10-02 14:18:07',lang:'et',outcome:'ok',source:'demo'}]});
    if (url.pathname === '/api/call-history') {
      if(historyMode==='failure')return reply({},503);
      let items=historyMode==='empty'?[]:[telephoneCall,browserCall];
      if(url.searchParams.get('channel')!=='all')items=items.filter(item=>item.channel===url.searchParams.get('channel'));
      if(url.searchParams.get('result')==='attention')items=items.filter(item=>item.needs_attention);
      if(url.searchParams.get('result')==='booked')items=items.filter(item=>item.bookings.length);
      return reply({items,summary:{total:items.length,active:0,with_booking:items.filter(item=>item.bookings.length).length,needs_attention:items.filter(item=>item.needs_attention).length},page:1,length:20,has_more:false,fetched_at:'2026-10-03T06:00:00Z',data_mode:'synthetic'});
    }
    if (url.pathname.startsWith('/api/call-history/')) {
      if(historyMode==='delayed')await new Promise(resolve=>releaseHistory=resolve);
      const item=url.pathname.endsWith(telephoneCall.id)?telephoneCall:browserCall;
      return reply({session:item,events:[{id:1,at:item.started_at,kind:'started',outcome:''},{id:2,at:item.started_at,kind:'recognized',outcome:''},{id:3,at:item.ended_at,kind:item.bookings.length?'booking_confirmed':'stt_unavailable',outcome:''},{id:4,at:item.ended_at,kind:'ended',outcome:item.outcome}]});
    }
    if (url.pathname === '/api/catalogue') return reply({services,providers:[{id:1,name:'Demo teenindaja',services:[1,2,3]}]});
    if (url.pathname === '/api/rooms') return reply({room_types:[]});
    if (url.pathname === '/api/stays') return reply({items:url.searchParams.get('date')===stayReceipt.date?[{id:stayReceipt.id,status:'confirmed',room_name:'Fiktiivne spaatoa näidis',checkin:stayReceipt.date,checkout:stayReceipt.checkout,nights:2,adults:2,children:0}]:[]});
    if (url.pathname === '/api/rooms') return reply({synthetic:true,room_types:[]});
    if (url.pathname === '/api/stays') return reply({synthetic:true,items:[]});
    if (url.pathname === '/api/bookings') {
      if (mode === 'delayed') await new Promise(resolve => releaseBooking = resolve);
      if (mode === 'failure') return reply({},503);
      const date = url.searchParams.get('date');
      const second = url.searchParams.get('page') === '2';
      const selected = second ? services.slice(0,1) : services;
      return reply({items:mode === 'empty' ? [] : selected.map((service,i)=>({id:second?201:i+101,service_name:service.name,provider_name:'Demo teenindaja',start_local:`${date} ${10+i*2}:00:00`,end_local:`${date} ${11+i*2}:00:00`,timezone:'Europe/Tallinn',time_state:'valid',status:'Booked'})),fetched_at:'2026-10-02T14:34:00+03:00',has_more:mode === 'empty'||second?false:'unknown'});
    }
    if (url.pathname === '/api/demo/session') return reply({session_id:'fixture-session',call_id:browserCall.id,greeting:'Tere! Olen Meretuule Demo Spa virtuaalne abiline. Millist teenust soovid proovida?'});
    if (url.pathname.startsWith('/api/demo/session/')) return reply({ok:true});
    if (url.pathname === '/api/turn') {
      turns++;
      const input = request.postDataJSON();
      if(input.audio_b64) audioUploads.push(Buffer.from(input.audio_b64,"base64"));
      return reply({text_heard:input.text || "Sünteetiline heliproov",input_status:input.audio_b64?"recognized":"typed",reply:'Klassikaline massaaž kestab 60 minutit. Mis päeval soovid tulla?',outcome:speechFails?'tts_failed':'ok',tts_failed:speechFails,warnings:speechFails?[{stage:'tts',code:'reply_audio_unavailable'}]:[],timings_ms:{stt:0,llm:400,tools:25,tts:75,total:500},audio_b64:'',turn_count:turns,expires_in_s:590,booking_changes:[]});
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
  await page.waitForFunction(()=>document.querySelectorAll('#history-list li').length===2);
  assert(await page.locator('#history-total').textContent()==='2','history count did not use server summary');
  await page.locator('#history-list button').first().click();
  await page.waitForFunction(()=>document.querySelectorAll('.history-timeline li').length===4);
  assert((await page.locator('#history-detail').textContent()).includes('Broneering #101'),'confirmed booking link missing');
  await page.locator('.history-booking button').click();
  await page.waitForFunction(()=>document.getElementById('booking-date').value==='2026-10-09');
  assert(await page.locator('#bookings tbody tr.highlight').count()===1,'history did not highlight the authoritative booking');
  await page.locator('#history-channel').selectOption('browser');
  await page.waitForFunction(()=>document.querySelectorAll('#history-list li').length===1);
  browserCall.bookings=[stayReceipt];
  await page.locator('#history-list button').click();
  await page.waitForFunction(()=>document.querySelector('.history-insight')?.textContent.includes('Kõnetuvastuse teenus'));
  await page.getByRole('button',{name:'Ava päeva peatumised'}).click();
  await page.waitForFunction(()=>document.getElementById('booking-date').value==='2026-10-12' && document.querySelector('#stays-list .stay-row'));
  assert((await page.locator('#stays-list').textContent()).includes(stayReceipt.id),'history room link did not open its actual day');
  assert(await page.locator('#stays-title').evaluate(el=>el===document.activeElement),'room history link did not focus the destination');
  browserCall.bookings=[];
  await page.locator('#history-channel').selectOption('all');
  await page.waitForFunction(()=>document.querySelectorAll('#history-list li').length===2);
  historyMode='failure'; await page.locator('#history-refresh').click();
  await page.waitForFunction(()=>document.getElementById('history-status').classList.contains('stale'));
  assert(await page.locator('#history-list li').count()===2,'failed history refresh removed stale rows');
  historyMode='empty'; await page.locator('#history-refresh').click();
  await page.waitForFunction(()=>!document.getElementById('history-empty').hidden);
  historyMode='loaded'; await page.locator('#history-refresh').click();
  await page.waitForFunction(()=>document.querySelectorAll('#history-list li').length===2);
  await page.locator('#history-list button').first().click();
  await page.waitForFunction(()=>document.querySelectorAll('.history-timeline li').length===4);
  await page.locator('.history-booking button').click();
  await page.waitForFunction(()=>document.getElementById('booking-date').value==='2026-10-09' && document.querySelector('#bookings tbody tr.highlight'));
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
  assert(await page.locator('#demo-timings').isVisible(),'turn timings missing');
  assert((await page.locator('#demo-models').textContent()).includes('openai/gpt-oss-120b'),'configured model missing');
  await page.screenshot({path:'output/playwright/after-conversation-desktop.png',fullPage:true});
  speechFails=true;
  await page.locator('#demo-text').fill('Küsin veel ühe küsimuse.');
  await page.locator('#demo-send').click();
  await page.waitForFunction(()=>!state.turnBusy && document.querySelectorAll('#demo-messages li').length===5);
  assert(await page.locator('#demo-warning').isVisible(),'speech failure warning missing');
  assert((await page.locator('#demo-warning').textContent()).includes('tekstina alles'),'speech failure omitted text fallback guidance');
  assert(await page.locator('#demo-messages .assistant-message').count()===3,'speech failure discarded text reply');
  await page.evaluate(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Fixture microphone permission denied','NotAllowedError');};});
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>document.getElementById('demo-status').classList.contains('error') && document.getElementById('demo-status').textContent.includes('Mikrofon'));
  assert((await page.locator('#demo-status').textContent()).includes('Mikrofon'),'microphone denial did not give guidance');
  const audioChecks=await page.evaluate(async()=>{
    const input=new Float32Array(48000); for(let i=0;i<input.length;i++)input[i]=Math.sin(2*Math.PI*500*i/48000)*.5;
    const encoded=await wav({chunks:[input],context:{sampleRate:48000}});
    const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0)), header=new DataView(bytes.buffer);
    return {rate:header.getUint32(24,true),channels:header.getUint16(22,true),samples:header.getUint32(40,true)/2};
  });
  assert(audioChecks.rate===16000 && audioChecks.channels===1 && audioChecks.samples===16000,'microphone WAV conversion changed audio framing');
  const beforeMic=turns;
  for(const amplitude of [0,.2]) {
    await page.evaluate(async amplitude=>{
      const context=new AudioContext({sampleRate:48000}), oscillator=context.createOscillator(), gain=context.createGain(), destination=context.createMediaStreamDestination();
      oscillator.frequency.value=500; gain.gain.value=amplitude;
      oscillator.connect(gain); gain.connect(destination); oscillator.start(); await context.resume();
      window.fixtureMic={context,oscillator,stream:destination.stream};
      navigator.mediaDevices.getUserMedia=async()=>destination.stream;
    },amplitude);
    await page.locator('#demo-mic').click();
    await page.waitForFunction(()=>state.mic?.frames>=8192);
    assert(await page.locator('#mic-feedback').isVisible(),'microphone feedback missing during capture');
    await page.locator('#demo-mic').click();
    await page.waitForFunction(()=>!state.mic && !state.turnBusy && !state.micStarting);
    assert(await page.evaluate(()=>window.fixtureMic.stream.getTracks().every(track=>track.readyState==='ended')),'stopped capture retained microphone tracks');
    await page.evaluate(async()=>{window.fixtureMic.oscillator.stop();await window.fixtureMic.context.close();delete window.fixtureMic;});
    if(!amplitude) {
      assert(turns===beforeMic,'digital silence reached the speech provider');
      assert((await page.locator('#demo-status').textContent()).includes('helisignaali'),'silent microphone guidance missing');
    }
  }
  assert(turns===beforeMic+1 && audioUploads.length===1,'voiced capture did not send exactly one turn');
  const uploaded=audioUploads[0];
  assert(uploaded.readUInt32LE(24)===16000 && uploaded.readUInt16LE(22)===1 && uploaded.readUInt16LE(34)===16,'captured microphone WAV format incorrect');
  let peak=0;for(let offset=44;offset<uploaded.length;offset+=2)peak=Math.max(peak,Math.abs(uploaded.readInt16LE(offset)));
  assert(peak>1000,'resampling lost the captured signal');
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
  historyMode='delayed'; await page.locator('#history-list button').first().click();
  await page.waitForFunction(()=>document.getElementById('history-detail').getAttribute('aria-busy')==='true');
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.getElementById('booking-section').getAttribute('aria-busy')==='true');
  await page.locator('#logout').click();
  releaseBooking();
  releaseHistory();
  await page.waitForFunction(()=>document.getElementById('connection-label').textContent==='Ühendamata');
  assert(await page.locator('#bookings tbody tr').count()===0,'logout retained private rows');
  assert(await page.locator('#demo-messages li').count()===0,'logout retained conversation');
  assert(await page.locator('#catalogue li').count()===0,'logout retained catalogue');
  assert(await page.locator('#history-list li').count()===0,'logout retained history');
  assert(!(await page.locator('#history-detail').textContent()).includes('Broneering #101'),'late history detail revived private data');
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
  await page.unroute('**/api/calls');
  await page.unroute('**/api/**');
  return {result:'passed',layouts,turns,errors,screenshots:5};
}
