const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag='div'){ this.tagName=tag.toUpperCase();this.value=''; this.textContent=''; this.hidden=false; this.disabled=false; this.type='password'; this.children=[]; this.dataset={}; this.listeners={}; this.classList={add(){},remove(){}}; }
  addEventListener(type,fn){this.listeners[type]=fn;}
  setAttribute(){}
  replaceChildren(...items){this.children=items;this.textContent='';}
  append(...items){this.children.push(...items);}
  appendChild(item){this.children.push(item);}
  contains(item){return this===item || this.children.some(child=>child.contains?.(item));}
  pause(){}
  focus(){this.focused=true;}
  removeAttribute(){}
  load(){}
}
const elements=new Map();
const element=id=>{if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id);};
const requests=[]; const intervals=[];
let pending=null;
const response=(data,status=200)=>({ok:status===200,status,headers:new Headers(),json:async()=>data});
const context=vm.createContext({console,Headers,URL,URLSearchParams,AbortController,DOMException,Intl,Date,JSON,Math,Promise,Uint8Array,ArrayBuffer,Blob,
  document:{hidden:false,getElementById:element,createElement:tag=>new Element(tag),createTextNode:t=>t,querySelector:s=>element(s),addEventListener(type,fn){if(type==='DOMContentLoaded')fn();}},
  window:{},navigator:{},location:{search:'',href:'https://fixture.invalid/'},history:{replaceState(){}},
  sessionStorage:{removeItem(){}},localStorage:{removeItem(){}},
  setTimeout:()=>1,clearTimeout(){},setInterval:fn=>{intervals.push(fn);return 1;},
   fetch:async(path,opts={})=>{requests.push({path,opts}); if(pending&&path.includes('/api/table-bookings'))return new Promise(resolve=>{pending.resolve=resolve;});
    if(path==='/api/status')return response({wired:{},capabilities:{}});
    if(path==='/api/calls')return response({calls:[]});
     if(path==='/api/tables')return response({tables:[],rules:{timezone:'Europe/Tallinn',max_party_size:6}});
    if(path==='/api/demo/session')return response({session_id:'fixture-session',call_id:'a'.repeat(32),greeting:'Fiktiivne demovestlus',expires_in_s:600});
     if(path.includes('/api/table-bookings'))return response({items:[],has_more:false,fetched_at:'2026-10-02T10:00:00Z'});
    return response({ok:true});}
});
vm.runInContext(fs.readFileSync(process.argv[4],'utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[3],'utf8').match(/<script>([\s\S]*?)<\/script>/)[1],context);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const run=s=>vm.runInContext(s,context);
(async()=>{
  await flush();
  assert.equal(run('bookingUi.kind'),'table','active composer is not restaurant-only');
  assert(requests.every(r=>r.path==='/api/status'),'private initial request');
  assert.equal(element('bookings').hidden,true,'signed-out table should be hidden');
  assert.equal(element('booking-placeholder').hidden,false,'signed-out guidance missing');
  assert.equal(element('token-field').hidden,false,'sign-in field missing');
  assert.equal(element('logout').hidden,true,'signed-out logout should be hidden');
  assert.equal(element('demo-start').disabled,false,'signed-out demo start cannot explain the sign-in prerequisite');
  assert.equal(element('demo-mic').disabled,false,'signed-out voice button cannot explain the sign-in prerequisite');
  await element('demo-start').listeners.click();
  assert.equal(element('token').focused,true,'demo start did not focus operator sign-in');
  assert(element('demo-status').textContent.includes('tunnus'),'demo start did not explain operator sign-in');
  element('token').focused=false;
  await element('demo-mic').listeners.click();
  assert.equal(element('token').focused,true,'voice button did not focus operator sign-in');
  assert(requests.every(r=>r.path==='/api/status'),'signed-out demo click sent a private request');
  element('token').value='fixture-operator';
  await run('connect()'); await flush();
   assert(requests.some(r=>r.path.includes('/api/table-bookings')),'no independent table readback');
  assert.equal(element('connection-badge').className,'connection-badge connected');
  assert.equal(element('token-field').hidden,true,'credential field shown after authentication');
  assert.equal(element('logout').hidden,false,'connected logout missing');
  assert.equal(element('booking-empty').hidden,false,'successful empty state missing');
  assert.equal(element('booking-placeholder').hidden,true,'empty schedule presented as locked');
  assert.equal(element('demo-mic').disabled,false,'connected voice button requires an unexplained separate session start');
  const connectedFetch=context.fetch;
  const tableOffer={table_offer_id:'table_offer_'+'a'.repeat(32),date:'2026-10-09',start_time:'18:00',start:'2026-10-09T18:00:00+03:00',end:'2026-10-09T20:00:00+03:00',party_size:3,duration_minutes:120,table_name:'Laud 3',capacity:4};
  const recap='Meretuule restoran. Fiktiivne külaline. 09.10.2026 kell 18:00, Europe/Tallinn. 3 inimest, 120 minutit, Laud 3.';
  context.fetch=async(path,opts={})=>{
    if(path.startsWith('/api/booking/')) {
      requests.push({path,opts});
      if(path.endsWith('/session'))return response({session_id:'table-session'});
      if(path.endsWith('/search'))return response({kind:'table',offers:[tableOffer]});
      if(path.endsWith('/prepare'))return response({kind:'table',hold_id:'held-table',recap:{kind:'table',date:tableOffer.date,start_time:tableOffer.start_time,party_size:3},recap_text:recap,recap_delivery_id:'c'.repeat(32)});
      if(path.endsWith('/recap'))return response({acknowledged:true,hold_id:'held-table'});
      if(path.endsWith('/confirm'))return response({ok:true,kind:'table',booking_id:'table_'+'a'.repeat(32),booking:{id:'table_'+'a'.repeat(32),date:'2026-10-09'}});
      if(path.endsWith('/cancel'))return response({ok:true,kind:'table'});
    }
    return connectedFetch(path,opts);
  };
  element('new-table-date').value='2026-10-09';element('new-start-time').value='18:00';element('new-party-size').value='3';
  await run('searchBooking()');
  const searchBody=JSON.parse(requests.find(r=>r.path==='/api/booking/search').opts.body);
  assert.deepEqual(searchBody,{session_id:'table-session',kind:'table',date:'2026-10-09',start_time:'18:00',party_size:3});
  await run('prepareBooking('+JSON.stringify(tableOffer)+')');
  assert.equal(element('booking-recap-text').textContent,recap,'client changed the canonical recap');
  assert.equal(element('booking-confirm').disabled,true,'preparation enabled confirmation before recap reading');
  assert.equal(element('booking-recap-read').focused,true,'prepared recap did not focus the next explicit reading action');
  assert(!requests.some(r=>r.path==='/api/booking/recap'),'preparation falsely acknowledged unread recap');
  assert.deepEqual(JSON.parse(requests.find(r=>r.path==='/api/booking/prepare').opts.body),{session_id:'table-session',kind:'table',guest_fixture_id:'guest-001',table_offer_id:tableOffer.table_offer_id});
  await run('acknowledgeBookingRecap()');
  const acknowledgments=requests.filter(r=>r.path==='/api/booking/recap');
  assert.deepEqual(JSON.parse(acknowledgments[0].opts.body),{session_id:'table-session',hold_id:'held-table',recap_delivery_id:'c'.repeat(32)});
  await run('acknowledgeBookingRecap()');
  assert.equal(requests.filter(r=>r.path==='/api/booking/recap').length,1,'one-use receipt was acknowledged twice');
  assert.equal(element('booking-confirm').disabled,false,'exact read acknowledgement did not enable confirmation');
  assert.equal(element('booking-confirm').focused,true,'reading hid the focused control without focusing confirmation');
  await run("mutateBooking('confirm')");
  assert.deepEqual(JSON.parse(requests.find(r=>r.path==='/api/booking/confirm').opts.body),{session_id:'table-session',kind:'table',consent:true,hold_id:'held-table'});
  await run("mutateBooking('cancel')");
  assert(!requests.some(r=>r.path==='/api/booking/cancel'),'cancellation skipped the second explicit step');
  element('booking-cancel-actions').hidden=false;
  await run("mutateBooking('cancel')");
  assert.deepEqual(JSON.parse(requests.find(r=>r.path==='/api/booking/cancel').opts.body),{session_id:'table-session',kind:'table',consent:true,booking_id:'table_'+'a'.repeat(32)});
  context.fetch=connectedFetch;
  const historyFixture={id:'a'.repeat(32),channel:'telephone',started_at:'2026-10-03T10:00:00Z',duration_s:30,recognized_turns:1,typed_turns:0,bookings:[
    {id:'table_'+'a'.repeat(32),kind:'table',action:'confirmed',date:'2026-10-09',start_local:'2026-10-09 18:00:00'},
    {id:'stay_'+'b'.repeat(32),kind:'stay',action:'confirmed',date:'2026-10-01',checkout:'2026-10-03'},
    {id:'17',kind:'slot',action:'cancelled',date:'2026-10-01',start_local:'2026-10-01 10:00:00'},
  ]};
  run('renderHistoryDetail('+JSON.stringify({session:historyFixture,events:[]})+')');
  const flatten=node=>[node,...node.children.flatMap(flatten)];
  const historyNodes=flatten(element('history-detail'));
  const bookingLinks=historyNodes.filter(node=>node.tagName==='BUTTON');
  assert.equal(bookingLinks.length,1,'archived stay/slot histories link to removed live panels');
  assert(historyNodes.some(node=>node.textContent.includes('Arhiveeritud hotellipeatumine')),'legacy stay was relabelled or lost');
  assert(historyNodes.some(node=>node.textContent.includes('Arhiveeritud spaa')),'legacy slot was relabelled or lost');
  await bookingLinks[0].listeners.click();
  assert.equal(element('booking-date').value,'2026-10-09');
  assert.equal(run('state.highlightId'),'table_'+'a'.repeat(32));
  assert.equal(element('bookings-title').focused,true,'table history destination was not focused');
  const awareRange=run("localBookingRange('2026-10-09T15:00:00Z','2026-10-09T17:00:00Z')");
  assert.equal(awareRange.time,'18:00 – 20:00','table aware instants were converted using device timezone');
  let microphoneAttempts=0;
  context.navigator.mediaDevices={getUserMedia:async()=>{microphoneAttempts++;throw new DOMException('Fixture permission denied','NotAllowedError');}};
  const readyFetch=context.fetch;
  context.fetch=async(path,opts)=>path==='/api/demo/session'?response({},503):readyFetch(path,opts);
  await element('demo-mic').listeners.click();
  assert.equal(run('state.sessionId'),null,'failed demo start produced a usable session');
  assert.equal(microphoneAttempts,0,'microphone opened before a demo session existed');
  assert.equal(element('demo-mic').disabled,false,'failed demo start trapped the voice button');
  context.fetch=readyFetch;
  const startsBefore=requests.filter(r=>r.path==='/api/demo/session').length;
  await element('demo-mic').listeners.click();
  assert.equal(run('state.sessionId'),'fixture-session','voice click did not start its demo session');
  assert.equal(microphoneAttempts,1,'voice click did not reach the microphone permission request');
  assert.equal(element('demo-status').className,'status error','microphone denial was silent');
  assert(element('demo-status').textContent.includes('Mikrofon'),'microphone denial did not explain recovery');
  assert.equal(element('demo-text').disabled,false,'microphone denial blocked text fallback');
  await element('demo-mic').listeners.click();
  assert.equal(requests.filter(r=>r.path==='/api/demo/session').length,startsBefore+1,'microphone retry created a second conversation');
  assert.equal(requests.filter(r=>r.path==='/api/turn').length,0,'denied microphone sent a conversation turn');
  await run('endDemo()');
  await run(`api('/api/turn',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})`);
  const post=requests.find(r=>r.path==='/api/turn');
  assert.equal(post.opts.headers.get('Content-Type'),'application/json');
  assert.equal(post.opts.headers.get('Authorization'),'Bearer fixture-operator');
  pending={};
  const read=run('loadBookings(true)');await flush();
  assert.equal(typeof pending.resolve,'function');
  run('logout()');
   pending.resolve(response({items:[{id:'table_'+'a'.repeat(32),table_name:'PRIVATE',party_size:3,start_local:'2026-10-02 18:00:00',end_local:'2026-10-02 20:00:00'}],has_more:false,fetched_at:'2026-10-02T10:00:00Z'}));
  await read; await flush();
  pending=null;
  assert.equal(run('state.bookings.length'),0,'late response revived private rows');
  assert.equal(element('token').value,'');
  const count=requests.length;
  for(const tick of intervals) await tick(); await flush();
  assert(requests.slice(count).every(r=>r.path==='/api/status'),'signed-out private poll');
  assert.equal(element('#bookings tbody').children.length,0);
  assert.equal(element('bookings').hidden,true,'logout retained booking table');
  assert.equal(element('booking-placeholder').hidden,false,'logout did not restore guidance');
  assert.equal(element('token-field').hidden,false,'logout did not restore sign-in field');
  element('token').value='fixture-operator';await run('connect()');await flush();
  run(`state.sessionId='fixture-session'`);
  let cancelled=false;
  context.fetch=async(path)=>{
     if(path==='/api/turn')return response({text_heard:'fixture',reply:'fixture',audio_b64:'',outcome:'tools_ok',booking_changes:[{id:'table_'+'a'.repeat(32),kind:'table',date:'2026-10-09',action:cancelled?'cancelled':'confirmed'}]});
     if(path.includes('/api/table-bookings'))return response({items:cancelled?[]:[{id:'table_'+'a'.repeat(32),table_name:'<img>',party_size:3,start_local:'2026-10-09 18:00:00',end_local:'2026-10-09 20:00:00',timezone:'Europe/Tallinn',time_state:'valid',status:'confirmed'}],fetched_at:'fixture',has_more:false});
    return response({calls:[]});
  };
  await run(`sendTurn({text:'confirm'})`); await flush();
  assert.equal(element('booking-date').value,'2026-10-09','did not select authoritative booked day');
   assert.equal(element('#bookings tbody').children[0].dataset.bookingId,'table_'+'a'.repeat(32));
  assert.equal(element('#bookings tbody').children[0].className,'highlight');
  const timeCell=element('#bookings tbody').children[0].children[2];
   assert.equal(timeCell.children[0].textContent,'18:00 – 20:00','local wall time changed');
  assert.equal(timeCell.children[1].textContent,'09.10.2026','local date changed');
  assert.equal(run("localBookingRange('2026-10-09 23:00:00','2026-10-10 01:00:00').time"),'2026-10-09 23:00:00 – 2026-10-10 01:00:00','overnight dates lost');
  assert.equal(element('bookings').hidden,false,'populated booking table hidden');
  assert.equal(element('demo-placeholder').hidden,true,'conversation introduction hides active chat');
  assert.equal(element('demo-messages').children[0].className,'user-message');
  assert.equal(element('demo-messages').children[1].className,'assistant-message');
  const normalFetch=context.fetch;
  context.fetch=async(path)=>path==='/api/turn'?response({text_heard:'fixture',reply:'Testbroneering on kinnitatud. Muu päring ebaõnnestus.',outcome:'tools_failed',booking_changes:[{id:'table_'+'a'.repeat(32),kind:'table',date:'2026-10-09',action:'confirmed'}]}):normalFetch(path);
  await run("sendTurn({text:'fixture'})"); await flush();
  assert(!element('demo-status').textContent.includes('edu ei ole kinnitatud'),'secondary read failure denied the completed write');
  context.fetch=normalFetch;
  const bookingCount=run('state.bookings.length');
  const successfulFetch=context.fetch;
   context.fetch=async(path)=>path.includes('/api/table-bookings')?response({},503):successfulFetch(path);
  await run('loadBookings(true)');
  assert.equal(run('state.bookings.length'),bookingCount,'provider error removed retained rows');
  assert.equal(element('booking-status').className,'status booking-status stale');
  assert.equal(element('bookings').hidden,false,'stale rows were hidden');
  context.fetch=successfulFetch;
  cancelled=true;await run(`sendTurn({text:'cancel'})`); await flush();
  assert.equal(element('#bookings tbody').children.length,0,'cancelled row did not disappear');
  assert.equal(element('bookings').hidden,true,'empty table shown after cancellation');
  assert.equal(element('booking-empty').hidden,false,'empty state missing after cancellation');
  context.fetch=async(path)=>{
    if(path==='/api/turn')return response({text_heard:'fixture',reply:'Fiktiivne peatumine kinnitatud.',audio_b64:'',outcome:'tools_ok',booking_changes:[{id:'stay_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',kind:'stay',date:'2026-10-12',action:'confirmed'}]});
     if(path.includes('/api/table-bookings'))return response({items:[],has_more:false,fetched_at:'fixture'});
    return response({calls:[]});
  };
  await run("sendTurn({text:'fixture'})"); await flush();
  assert.equal(element('booking-date').value,'2026-10-09','archived stay receipt redirected the restaurant readback');
  let stopped=0;
  context.navigator.mediaDevices={getUserMedia:async()=>({getTracks:()=>[{stop(){stopped++;}}]})};
  context.window.AudioContext=class {constructor(){throw Error('fixture setup failure');}};
  await run('toggleMic()');
  assert.equal(stopped,1,'microphone setup failure leaked active tracks');
  context.fetch=async()=>response(null,403);
  await run('loadBookings(true)');
  assert.equal(run('state.connected'),false,'403 did not sign out');
  assert.equal(run('state.bookings.length'),0);
  assert.equal(element('auth-status').className,'status error','auth error not visibly identified');
  let permissionAfterLogout=0;
  context.navigator.mediaDevices={getUserMedia:async()=>{permissionAfterLogout++;throw new DOMException('Fixture denied','NotAllowedError');}};
   context.fetch=async(path)=>response(path==='/api/calls'?{calls:[{at:'PRIVATE',lang:'et',outcome:'ok'}]}:path==='/api/tables'?{tables:[{id:'PRIVATE',name:'PRIVATE',capacity:2}],rules:{}}:path==='/api/demo/session'?{session_id:'PRIVATE',greeting:'PRIVATE'}:path==='/api/turn'?{text_heard:'PRIVATE',reply:'PRIVATE',audio_b64:''}:{items:[{id:'table_'+'a'.repeat(32),table_name:'PRIVATE'}],fetched_at:'fixture',has_more:false});
  run(`const originalApi=api; let logoutAfter=null; api=async(path,options)=>{const data=await originalApi(path,options); if(logoutAfter && path.startsWith(logoutAfter)) logout(); return data;};`);
   for (const [call,path] of [['loadBookings(true)','/api/table-bookings'],['loadCatalogue()','/api/tables'],['loadCalls()','/api/calls'],['startDemo()','/api/demo/session'],['toggleMic()','/api/demo/session'],["sendTurn({text:'fixture'})",'/api/turn']]) {
    run('logoutAfter=null');element('token').value='fixture-operator';await run('connect()');
    if(path==='/api/turn')run("state.sessionId='fixture-session'");
    run(`logoutAfter=${JSON.stringify(path)}`);await run(call);await flush();
    assert.equal(run('state.connected'),false,call+' restored auth');
    assert.equal(run('state.bookings.length'),0,call+' restored state after api returned');
    for(const id of ['#bookings tbody','catalogue','calls','demo-messages']) assert.equal(element(id).children.length,0,call+' restored '+id);
    assert.equal(run('state.sessionId'),null,call+' restored session');
  }
  assert.equal(permissionAfterLogout,0,'late session start opened the microphone after logout');
  run("logoutAfter='/api/calls'");element('token').value='fixture-operator';await run('connect()');
  assert.equal(run('state.connected'),false,'connect restored auth after logout');
  // A lost connection must release the UI; a write timeout must not retry.
  run('api=originalApi; logoutAfter=null; logout()');
  const deadlines=new Map();let timerId=0;
  context.setTimeout=(fn,delay)=>{deadlines.set(++timerId,{fn,delay});return timerId;};
  context.clearTimeout=id=>deadlines.delete(id);
  let stalledRequests=0;
  context.fetch=async(path,opts)=>{stalledRequests++;return new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(new DOMException('Fixture network aborted','AbortError'))));};
  const expire=()=>{assert.equal(deadlines.size,1,'network request has no bounded deadline');const timer=[...deadlines.values()][0];assert(timer.delay>0 && timer.delay<=120000,'unbounded network wait');timer.fn();};
  element('token').value='fixture-operator';const connecting=run('connect()');await flush();expire();await connecting;
  assert.equal(run('state.credential'),'','timed-out sign-in trapped the credential');
  assert.equal(element('connect').disabled,false,'timed-out sign-in trapped the connect button');
  assert.equal(element('auth-status').className,'status error','sign-in timeout was silent');
  run("state.credential='fixture-operator';state.connected=true;state.fetchedAt='fixture';state.bookings=[{id:42}]");
  const stalledRead=run('loadBookings(true)');await flush();expire();await stalledRead;
  assert.equal(run('state.readBusy'),false,'read timeout left controls locked');
  assert.equal(run('state.bookings.length'),1,'read timeout discarded stale data');
  assert.equal(element('booking-status').className,'status booking-status stale','read timeout was silent');
  run("state.sessionId='fixture-session'");const beforeWrite=stalledRequests;
  const stalledWrite=run("sendTurn({text:'fixture'})");await flush();expire();await stalledWrite;
  assert.equal(stalledRequests,beforeWrite+1,'timed-out write was retried');
  assert.equal(run('state.turnBusy'),false,'write timeout left controls locked');
  assert.equal(element('demo-status').className,'status error','write timeout was silent');
  assert(element('demo-status').textContent.includes('Ebaselge'),'write timeout omitted uncertain-outcome guidance');
  assert(element('demo-status').textContent.toLowerCase().includes('ära korda'),'write timeout encouraged retry instead of independent readback');
  assert.equal(deadlines.size,0,'completed requests leaked timeout timers');
  console.log('ui_checks_ok');
})().catch(e=>{console.error(e);process.exitCode=1;});
