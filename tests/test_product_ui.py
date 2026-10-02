"""Native dashboard auth lifecycle; no frontend framework or test dependency."""

import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app/dashboard/static/dashboard.js"


def test_form_inputs_have_names_and_explicit_autocomplete():
    inputs = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attributes):
            if tag == "input":
                inputs.append(dict(attributes))

    Parser().feed((ROOT / "app/dashboard/static/index.html").read_text())
    assert inputs
    for field in inputs:
        assert field.get("name"), field["id"]
        assert field.get("autocomplete"), field["id"]


def test_product_controls_and_no_persistent_credential():
    html = (ROOT / "app/dashboard/static/index.html").read_text()
    for control in (
        "connect",
        "logout",
        "bookings",
        "booking-date",
        "booking-prev",
        "booking-next",
        "demo-start",
        "demo-text",
        "demo-send",
        "demo-mic",
        "demo-audio",
        "demo-end",
    ):
        assert f'id="{control}"' in html, f"missing {control}"
    assert "HTTP" in html and "väljamõeldud" in html
    assert "Telefonikõne: kinnitamata" in html
    assert "„Jah, kinnitan.”" in html and "„Jah, tühista.”" in html
    assert 'rel="icon"' in html and "data:image/svg+xml" in html
    assert SCRIPT.exists(), "product dashboard controller missing"
    js = SCRIPT.read_text()
    assert "sessionStorage.setItem" not in js
    assert "localStorage.setItem" not in js
    assert "audio/mpeg" in js
    assert "getUserMedia" in js and "getTracks" in js
    assert "quote_fidelity" not in js
    assert "LiveKit ühendatud" not in js
    assert "innerHTML" not in js


def test_auth_headers_logout_late_response_and_signed_out_poll():
    assert SCRIPT.exists(), "product dashboard controller missing"
    script = r"""
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
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8').match(/<script>([\s\S]*?)<\/script>/)[1],context);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const run=s=>vm.runInContext(s,context);
(async()=>{
  await flush();
  assert(requests.every(r=>r.path==='/api/status'),'private initial request');
  element('token').value='fixture-operator';
  await run('connect()'); await flush();
  assert(requests.some(r=>r.path.includes('/api/bookings')),'no provider schedule');
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
  cancelled=true;await run(`sendTurn({text:'cancel'})`);
  assert.equal(element('#bookings tbody').children.length,0,'cancelled row did not disappear');
  let stopped=0;
  context.navigator.mediaDevices={getUserMedia:async()=>({getTracks:()=>[{stop(){stopped++;}}]})};
  context.window.AudioContext=class {constructor(){throw Error('fixture setup failure');}};
  await run('toggleMic()');
  assert.equal(stopped,1,'microphone setup failure leaked active tracks');
  context.fetch=async()=>response({},403);
  await run('loadBookings(true)');
  assert.equal(run('state.connected'),false,'403 did not sign out');
  assert.equal(run('state.bookings.length'),0);
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
  console.log('ui_checks_ok');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, str(SCRIPT), str(SCRIPT.with_name("index.html"))],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ui_checks_ok", "UI checks did not finish"
