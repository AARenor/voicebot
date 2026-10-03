const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(){ this.value=''; this.textContent=''; this.hidden=false; this.disabled=false; this.type='password'; this.children=[]; this.dataset={}; this.listeners={}; this.classList={add(){},remove(){}}; }
  addEventListener(type,fn){this.listeners[type]=fn;}
  setAttribute(){}
  replaceChildren(...items){this.children=items;this.textContent='';}
  append(...items){this.children.push(...items);}
  appendChild(item){this.children.push(item);}
  pause(){}
  removeAttribute(){}
  load(){}
}
const elements=new Map();
const element=id=>{if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id);};
const requests=[]; const intervals=[];
let pending=null;
const response=(data,status=200)=>({ok:status===200,status,headers:new Headers(),json:async()=>data});
const context=vm.createContext({console,Headers,URL,URLSearchParams,AbortController,DOMException,Intl,Date,JSON,Math,Promise,Uint8Array,ArrayBuffer,Blob,
  document:{hidden:false,getElementById:element,createElement:()=>new Element(),createTextNode:t=>t,querySelector:s=>element(s),addEventListener(type,fn){if(type==='DOMContentLoaded')fn();}},
  window:{},navigator:{},location:{search:'',href:'https://fixture.invalid/'},history:{replaceState(){}},
  sessionStorage:{removeItem(){}},localStorage:{removeItem(){}},
  setTimeout:()=>1,clearTimeout(){},setInterval:fn=>{intervals.push(fn);return 1;},
  fetch:async(path,opts={})=>{requests.push({path,opts}); if(pending&&path.includes('/api/bookings'))return new Promise(resolve=>{pending.resolve=resolve;});
    if(path==='/api/status')return response({wired:{},capabilities:{}});
    if(path==='/api/calls')return response({calls:[]});
    if(path==='/api/catalogue')return response({services:[],providers:[]});
    if(path.includes('/api/bookings'))return response({items:[],has_more:false,fetched_at:'2026-10-02T10:00:00Z'});
    return response({ok:true});}
});
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[3],'utf8').match(/<script>([\s\S]*?)<\/script>/)[1],context);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const run=s=>vm.runInContext(s,context);
(async()=>{
  await flush();
  assert(requests.every(r=>r.path==='/api/status'),'private initial request');
  assert.equal(element('bookings').hidden,true,'signed-out table should be hidden');
  assert.equal(element('booking-placeholder').hidden,false,'signed-out guidance missing');
  assert.equal(element('token-field').hidden,false,'sign-in field missing');
  assert.equal(element('logout').hidden,true,'signed-out logout should be hidden');
  element('token').value='fixture-operator';
  await run('connect()'); await flush();
  assert(requests.some(r=>r.path.includes('/api/bookings')),'no provider schedule');
  assert.equal(element('connection-badge').className,'connection-badge connected');
  assert.equal(element('token-field').hidden,true,'credential field shown after authentication');
  assert.equal(element('logout').hidden,false,'connected logout missing');
  assert.equal(element('booking-empty').hidden,false,'successful empty state missing');
  assert.equal(element('booking-placeholder').hidden,true,'empty schedule presented as locked');
  await run(`api('/api/turn',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})`);
  const post=requests.find(r=>r.path==='/api/turn');
  assert.equal(post.opts.headers.get('Content-Type'),'application/json');
  assert.equal(post.opts.headers.get('Authorization'),'Bearer fixture-operator');
  pending={};
  const read=run('loadBookings(true)');await flush();
  assert.equal(typeof pending.resolve,'function');
  run('logout()');
  pending.resolve(response({items:[{id:42,service_name:'PRIVATE',provider_name:'PRIVATE',start_local:'2026-10-02 10:00:00',end_local:'2026-10-02 11:00:00'}],has_more:false,fetched_at:'2026-10-02T10:00:00Z'}));
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
    if(path==='/api/turn')return response({text_heard:'fixture',reply:'fixture',audio_b64:'',outcome:'tools_ok',booking_changes:[{id:'42',date:'2026-10-09',action:cancelled?'cancelled':'confirmed'}]});
    if(path.includes('/api/bookings'))return response({items:cancelled?[]:[{id:42,service_name:'<img>',provider_name:'Demo',start_local:'2026-10-09 10:00:00',end_local:'2026-10-09 11:00:00',timezone:'Europe/Tallinn',time_state:'valid',status:'Booked'}],fetched_at:'fixture',has_more:false});
    return response({calls:[]});
  };
  await run(`sendTurn({text:'confirm'})`);
  assert.equal(element('booking-date').value,'2026-10-09','did not select authoritative booked day');
  assert.equal(element('#bookings tbody').children[0].dataset.bookingId,'42');
  assert.equal(element('#bookings tbody').children[0].className,'highlight');
  const timeCell=element('#bookings tbody').children[0].children[2];
  assert.equal(timeCell.children[0].textContent,'10:00 – 11:00','local wall time changed');
  assert.equal(timeCell.children[1].textContent,'09.10.2026','local date changed');
  assert.equal(run("localBookingRange('2026-10-09 23:00:00','2026-10-10 01:00:00').time"),'2026-10-09 23:00:00 – 2026-10-10 01:00:00','overnight dates lost');
  assert.equal(element('bookings').hidden,false,'populated booking table hidden');
  assert.equal(element('demo-placeholder').hidden,true,'conversation introduction hides active chat');
  assert.equal(element('demo-messages').children[0].className,'user-message');
  assert.equal(element('demo-messages').children[1].className,'assistant-message');
  const normalFetch=context.fetch;
  context.fetch=async(path)=>path==='/api/turn'?response({text_heard:'fixture',reply:'Testbroneering on kinnitatud. Muu päring ebaõnnestus.',outcome:'tools_failed',booking_changes:[{id:'42',date:'2026-10-09',action:'confirmed'}]}):normalFetch(path);
  await run("sendTurn({text:'fixture'})");
  assert(!element('demo-status').textContent.includes('edu ei ole kinnitatud'),'secondary read failure denied the completed write');
  context.fetch=normalFetch;
  const bookingCount=run('state.bookings.length');
  const successfulFetch=context.fetch;
  context.fetch=async(path)=>path.includes('/api/bookings')?response({},503):successfulFetch(path);
  await run('loadBookings(true)');
  assert.equal(run('state.bookings.length'),bookingCount,'provider error removed retained rows');
  assert.equal(element('booking-status').className,'status booking-status stale');
  assert.equal(element('bookings').hidden,false,'stale rows were hidden');
  context.fetch=successfulFetch;
  cancelled=true;await run(`sendTurn({text:'cancel'})`);
  assert.equal(element('#bookings tbody').children.length,0,'cancelled row did not disappear');
  assert.equal(element('bookings').hidden,true,'empty table shown after cancellation');
  assert.equal(element('booking-empty').hidden,false,'empty state missing after cancellation');
  context.fetch=async(path)=>{
    if(path==='/api/turn')return response({text_heard:'fixture',reply:'Fiktiivne peatumine kinnitatud.',audio_b64:'',outcome:'tools_ok',booking_changes:[{id:'stay_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',kind:'stay',date:'2026-10-12',action:'confirmed'}]});
    if(path.includes('/api/stays'))return response({items:[{id:'stay_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',status:'confirmed',room_name:'Demo tuba',checkin:'2026-10-12',checkout:'2026-10-14',nights:2,adults:2,children:0}]});
    if(path.includes('/api/bookings'))return response({items:[],has_more:false,fetched_at:'fixture'});
    return response({calls:[]});
  };
  await run("sendTurn({text:'fixture'})");
  assert.equal(element('booking-date').value,'2026-10-12','voice room receipt did not select its authoritative arrival day');
  assert.equal(element('overview-stays').textContent,'1','voice room receipt did not refresh active stays');
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
  context.fetch=async(path)=>response(path==='/api/calls'?{calls:[{at:'PRIVATE',lang:'et',outcome:'ok'}]}:path==='/api/catalogue'?{services:[{id:1,name:'PRIVATE',duration:30}],providers:[]}:path==='/api/demo/session'?{session_id:'PRIVATE',greeting:'PRIVATE'}:path==='/api/turn'?{text_heard:'PRIVATE',reply:'PRIVATE',audio_b64:''}:{items:[{id:42,service_name:'PRIVATE'}],fetched_at:'fixture',has_more:false});
  run(`const originalApi=api; let logoutAfter=null; api=async(path,options)=>{const data=await originalApi(path,options); if(logoutAfter && path.startsWith(logoutAfter)) logout(); return data;};`);
  for (const [call,path] of [['loadBookings(true)','/api/bookings'],['loadCatalogue()','/api/catalogue'],['loadCalls()','/api/calls'],['startDemo()','/api/demo/session'],["sendTurn({text:'fixture'})",'/api/turn']]) {
    run('logoutAfter=null');element('token').value='fixture-operator';await run('connect()');
    if(path==='/api/turn')run("state.sessionId='fixture-session'");
    run(`logoutAfter=${JSON.stringify(path)}`);await run(call);await flush();
    assert.equal(run('state.connected'),false,call+' restored auth');
    assert.equal(run('state.bookings.length'),0,call+' restored state after api returned');
    for(const id of ['#bookings tbody','catalogue','calls','demo-messages']) assert.equal(element(id).children.length,0,call+' restored '+id);
    assert.equal(run('state.sessionId'),null,call+' restored session');
  }
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
