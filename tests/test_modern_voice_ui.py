"""Deterministic production-JS checks; media decoding belongs to browser checks."""

import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app/dashboard/static"


def test_voice_selector_is_native_labeled_and_keeps_language_default() -> None:
    tags = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append((tag, dict(attrs)))

    Parser().feed((STATIC / "index.html").read_text())
    assert any(
        tag == "label" and attrs.get("for") == "demo-voice" for tag, attrs in tags
    )
    voice = next(
        attrs
        for tag, attrs in tags
        if tag == "select" and attrs.get("id") == "demo-voice"
    )
    assert voice.get("name") and voice.get("aria-describedby")
    assert 'value="auto"' in (STATIC / "index.html").read_text()


@pytest.mark.parametrize(
    "group",
    [
        "catalog",
        "receipt",
        "stream",
        "endpoint",
        "bounds",
        "lifecycle",
        "underrun",
        "wire",
    ],
)
def test_modern_voice_production_js(group: str) -> None:
    result = subprocess.run(
        ["node", "-e", VM_CHECKS, str(STATIC), group],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"modern_voice_{group}_ok"


VM_CHECKS = r"""
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const root=process.argv[1], group=process.argv[2];
class Element {
  constructor(){Object.assign(this,{value:'',textContent:'',hidden:false,disabled:false,children:[],dataset:{},listeners:{},paused:true,ended:false,duration:2,currentTime:0,played:{length:0},classList:{add(){},remove(){}}});}
  addEventListener(t,f){this.listeners[t]=f;} removeEventListener(t){delete this.listeners[t];}
  setAttribute(){} removeAttribute(){} replaceChildren(...v){this.children=v;this.textContent='';}
  append(...v){this.children.push(...v);} appendChild(v){this.append(v);}
  insertBefore(v,b){this.children=this.children.filter(x=>x!==v);this.children.splice(this.children.indexOf(b),0,v);}
  pause(){this.paused=true;} load(){} focus(){} play(){this.paused=false;this.onplaying?.();return Promise.resolve();}
}
const elements=new Map(), el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const requests=[], timers=new Map(), urls=[], revoked=[];let timerId=0;
const profiles=['azure','elevenlabs','google','cartesia'].map(id=>({id,label:id,languages:id==='cartesia'?['en','ru']:['et','en','ru'],configured:id!=='google',available:id!=='google',disabled_reason:id==='google'?'missing_credentials':null,streaming:id!=='google'}));
let catalog={voices:profiles,endpointing_ms:650}, turnResponse=null;
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
class MSE {
  static isTypeSupported(t){return t==='audio/mpeg';}
  constructor(){this.readyState='closed';queueMicrotask(()=>{this.readyState='open';this.onsourceopen?.();});}
  addSourceBuffer(){this.buffer={updating:false,appendBuffer:bytes=>{appends.push([...bytes]);this.buffer.updating=true;queueMicrotask(()=>{if(!holdAppends){this.buffer.updating=false;this.buffer.onupdateend?.();}});},abort(){this.updating=false;}};return this.buffer;}
  endOfStream(){this.readyState='ended';} removeSourceBuffer(){}
}
let holdAppends=false;const appends=[];
const URLStub=class extends URL {};
URLStub.createObjectURL=o=>{urls.push(o);return 'blob:fixture/'+urls.length;};URLStub.revokeObjectURL=u=>revoked.push(u);
const context=vm.createContext({console,Headers,Response,ReadableStream,TextDecoder,TextEncoder,URL:URLStub,URLSearchParams,AbortController,DOMException,Intl,Date,JSON,Math,Promise,Uint8Array,ArrayBuffer,DataView,Float32Array,Blob,atob,btoa,queueMicrotask,
  document:{hidden:false,getElementById:el,createElement:()=>new Element(),createTextNode:t=>t,querySelector:el,querySelectorAll:()=>[],addEventListener(){}},
  window:{MediaSource:MSE},navigator:{},location:{search:'',href:'http://127.0.0.1:8765/'},history:{replaceState(){}},sessionStorage:{removeItem(){}},localStorage:{removeItem(){}},
  setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},clearTimeout:id=>timers.delete(id),
  fetch:async(path,opts={})=>{requests.push({path,opts});if(path==='/api/demo/voices')return json(catalog);if(path==='/api/turn')return turnResponse;
    if(path==='/api/demo/session')return json({session_id:'fixture',language:'en',greeting:'Hi',audio_b64:''});
    if(path.startsWith('/api/demo/session/'))return json({},503);
    return json({items:[],calls:[],services:[],providers:[],summary:{},has_more:false,fetched_at:'fixture'});}
});
vm.runInContext(fs.readFileSync(root+'/call-history.js','utf8'),context);
vm.runInContext(fs.readFileSync(root+'/dashboard.js','utf8'),context);
const run=s=>vm.runInContext(s,context), flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const connected=()=>run("state.credential='fixture-operator';state.connected=true;state.sessionId='fixture';state.demoLanguage='en';controls()");
const receipt='a'.repeat(32), reply={type:'reply',reply:'<img onerror=bad> guarded recap',language:'en',audio_type:'audio/mpeg'};
const chunk={type:'audio',seq:0,audio_b64:'SUQz'};
const done={type:'done',reply:reply.reply,language:'en',text_heard:'fixture question',audio_type:'audio/mpeg',audio_b64:'',outcome:'ok',recap_delivery_id:receipt,booking_changes:[],voice:{requested:'azure',effective:'azure',language:'en',fallback:false,reason:null,streaming:true}};
function streamed(){let controller;const body=new ReadableStream({start(c){controller=c;}});turnResponse=new Response(body,{headers:{'Content-Type':'application/x-ndjson'}});return {write:e=>controller.enqueue(new TextEncoder().encode(typeof e==='string'?e:JSON.stringify(e)+'\n')),close:()=>controller.close()};}
function ended(start=0,end=2){const audio=el('demo-audio');audio.currentTime=2;audio.ended=true;audio.played={length:1,start:()=>start,end:()=>end};audio.onended?.();}
async function streamTurn(events,tail=''){const s=streamed(), task=run("sendTurn({text:'fixture'})");for(const e of events)s.write(e);if(tail)s.write(tail);s.close();await task;await flush();return task;}
async function checks(){
  if(group==='underrun'){
    connected();context.data={audio_b64:'SUQz',audio_type:'audio/mpeg',recap_delivery_id:receipt};
    run('playReply(data)');const audio=el('demo-audio');audio.currentTime=.2;audio.onwaiting?.();
    audio.onplaying?.();ended();assert.equal(run('state.recapDeliveryId'),null,'resumed underrun granted automatic recap receipt');
    assert.equal(el('demo-recap-read').hidden,false,'underrun removed explicit text-reading acknowledgment');
    const staleWaiting=audio.onwaiting;run('stopAudio();playReply(data)');staleWaiting?.();ended();
    assert.equal(run('state.recapDeliveryId'),receipt,'old underrun callback disqualified newer playback');
    run('stopAudio()');assert.equal(audio.onwaiting,null,'cleanup retained underrun handler');assert.equal(audio.onstalled,null,'cleanup retained stalled handler');
  }
  if(group==='wire'){
    connected();const chunks=Array.from({length:256},(_,seq)=>({type:'audio',seq,audio_b64:Buffer.alloc(32768).toString('base64')}));
    await streamTurn([reply,...chunks,done]);
    assert.equal(run('state.awaitingRecapId'),receipt,'server-valid 8 MiB MP3 was rejected after base64 expansion');
    assert.equal(run('state.playback.complete && state.playback.eof'),true,'bounded maximum stream lost terminal metadata');
    ended();assert.equal(run('state.recapDeliveryId'),receipt);
  }
 if(group==='catalog'){
   assert.equal(el('demo-voice').disabled,true,'signed-out voice selection is not disabled');
   connected();run('state.sessionId=null');await run('loadVoices()');
   assert.equal(run('state.demoVoice'),'azure','Azure is not the default');
   assert.equal(el('demo-voice').children.find(o=>o.value==='google').disabled,true,'missing credentials remained selectable');
   assert(el('demo-voice-help').textContent.includes('missing_credentials'),'closed reason/setup guidance missing');
   el('demo-voice').value='elevenlabs';run('changeDemoVoice()');await run('startDemo()');
   assert.equal(JSON.parse(requests.find(r=>r.path==='/api/demo/session').opts.body).voice,'elevenlabs','session creation omitted selected voice');
   el('demo-voice').value='azure';run('changeDemoVoice()');assert.equal(run('state.demoVoice'),'elevenlabs','active voice changed');
   run("state.sessionId=null;state.demoLanguage='et';renderVoices()");assert.equal(el('demo-voice').children.find(o=>o.value==='cartesia').disabled,true,'Cartesia offers unsupported Estonian');
   run("state.demoLanguage='auto';renderVoices()");assert(el('demo-voice').children.find(o=>o.value==='cartesia').textContent.includes('Azure'),'AUTO hides Cartesia Estonian fallback');
   catalog={};await run('loadVoices()');assert.equal(run('state.demoVoice'),'azure');assert.equal(el('demo-voice').children.filter(o=>!o.disabled).length,1,'legacy catalog optimistically enabled modern providers');
   assert(el('demo-voice-help').textContent.includes('catalog_unavailable'),'legacy readiness is not honest');
   run("state.demoVoice='elevenlabs';renderVoiceResult({})");assert(!el('demo-voice-result').textContent.includes('elevenlabs'),'missing effective metadata pretends selected voice was used');
   run("renderVoiceResult({tts_failed:true,voice:{requested:'elevenlabs',effective:'elevenlabs',language:'en',fallback:false,reason:null,streaming:true}})");assert(!el('demo-voice-result').textContent.includes('ElevenLabs'),'failed speech pretends selected voice was used');
 }
 if(group==='receipt'){
   connected();const data={audio_b64:'SUQz',audio_type:'audio/mpeg',recap_delivery_id:receipt};
   context.data=data;run('playReply(data)');ended(1.9);assert.equal(run('state.recapDeliveryId'),null,'seek-to-end granted playback receipt');
   run('stopAudio();playReply(data)');const stale=el('demo-audio').onended;ended();assert.equal(run('state.recapDeliveryId'),receipt,'full coverage did not grant receipt');
   run('stopAudio();playReply(data)');stale();assert.equal(run('state.recapDeliveryId'),null,'same-session stale epoch granted receipt');
   run('stopAudio();playReply(data)');el('demo-audio').src='blob:fixture/foreign';ended();assert.equal(run('state.recapDeliveryId'),null,'foreign audio identity granted receipt');
   run('stopAudio();playReply(data)');ended(0,1.97);assert.equal(run('state.recapDeliveryId'),null,'missing final audio coverage granted receipt');
   el('demo-audio').play=()=>Promise.reject(Error('blocked'));run('stopAudio();playReply(data)');await flush();ended();assert.equal(run('state.recapDeliveryId'),null,'blocked play granted receipt');
   assert.equal(el('demo-recap-read').hidden,false,'blocked play removed explicit reading');
   run('logout()');stale();assert.equal(run('state.recapDeliveryId'),null,'logout callback revived receipt');assert.equal(run('state.audioUrl'),null);
 }
 if(group==='stream'){
   connected();const s=streamed(), task=run("sendTurn({text:'fixture'})");s.write(reply);s.write(chunk);await flush();
   assert.equal(requests.find(r=>r.path==='/api/turn').opts.headers.get('Accept'),'application/x-ndjson','turn does not negotiate streaming');
   assert.equal(el('demo-messages').children.length,1,'guarded text did not render before done');assert.equal(el('demo-messages').children[0].children[1].textContent,reply.reply,'reply text was not rendered safely');
   assert.equal(appends.length,1,'first native MP3 append waited for done');assert.equal(el('demo-audio').paused,false,'native playback did not start before done');
   assert.equal(run('state.awaitingRecapId'),null,'first chunk armed a receipt');s.write(done);await flush();assert.equal(run('state.awaitingRecapId'),null,'done before EOF armed receipt');s.close();await task;await flush();
   assert.equal(el('demo-messages').children.length,2,'done duplicated guarded reply');assert.equal(run('state.recapDeliveryId'),null,'EOF alone granted receipt');ended();assert.equal(run('state.recapDeliveryId'),receipt,'complete native playback lost receipt');
   const stale=el('demo-audio').onended;await streamTurn([reply,chunk],'{');stale();assert.equal(run('state.recapDeliveryId'),null,'truncation granted receipt');assert.equal(run('state.awaitingRecapId'),null,'truncation enabled reading');
   for(const events of [[reply,{...chunk,seq:1},done],[reply,chunk,done,done],[reply,chunk,{...done,reply:'different'}],[reply,{...chunk,audio_b64:'%%%'} ,done],[{...reply,recap_delivery_id:receipt},chunk,done],[reply,done],[reply,chunk,{...done,tts_failed:true}],[reply,chunk,{...done,audio_b64:'SUQz'}]]){
     await streamTurn(events);ended();assert.equal(run('state.recapDeliveryId'),null,'invalid/failed stream granted receipt');assert.equal(run('state.awaitingRecapId'),null,'invalid/failed stream enabled reading');
   }
   await streamTurn([reply], 'x'.repeat(300000));assert.equal(run('state.awaitingRecapId'),null,'unbounded line accepted');
   holdAppends=true;const queued=streamed(), queuedTask=run("sendTurn({text:'fixture'})");queued.write(reply);queued.write(chunk);queued.write(done);queued.close();await queuedTask;ended();assert.equal(run('state.recapDeliveryId'),null,'unfinished append granted receipt');holdAppends=false;
   const source=urls.at(-1);source.buffer.updating=false;source.buffer.onupdateend?.();assert.equal(run('state.recapDeliveryId'),null,'append completion reused premature ended');
   context.window.MediaSource=undefined;const count=urls.length, blob=streamed(), blobTask=run("sendTurn({text:'fixture'})");blob.write(reply);blob.write(chunk);await flush();assert.equal(urls.length,count,'Blob fallback played partial stream');blob.write(done);blob.close();await blobTask;await flush();assert(urls.at(-1) instanceof Blob,'unsupported MSE did not use native Blob');ended();assert.equal(run('state.recapDeliveryId'),receipt);
   context.window.MediaSource=MSE;const ending=streamed(), endTask=run("sendTurn({text:'fixture'})");ending.write(reply);ending.write(chunk);await flush();
   const endRequest=requests.filter(r=>r.path==='/api/turn').at(-1);await run('endDemo()');assert(endRequest.opts.signal.aborted,'end during stream did not abort reader');await endTask;assert.equal(run('state.recapDeliveryId'),null,'failed end retained playback receipt');
   const pending=streamed(), pendingTask=run("sendTurn({text:'fixture'})");pending.write(reply);pending.write(chunk);await flush();const request=requests.filter(r=>r.path==='/api/turn').at(-1);run('logout()');assert(request.opts.signal.aborted,'logout did not abort reader fetch');await pendingTask;assert.equal(el('demo-messages').children.length,0,'late stream revived private text');
   assert.equal(requests.filter(r=>r.path==='/api/turn').length,15,'stream failure automatically retried POST');
 }
 if(group==='endpoint'){
   assert.equal(run('state.endpointingMs'),650,'endpointing default is not 650 ms');
   connected();run('state.sessionId=null');await run('loadVoices()');
   for(const bad of [0,5000,'650',null]){catalog={voices:profiles,endpointing_ms:bad};await run('loadVoices()');assert.equal(run('state.endpointingMs'),650,'invalid endpointing setting accepted');}
   connected();let stopped=0, sampleRate=48000;context.navigator.mediaDevices={getUserMedia:async()=>({getTracks:()=>[{stop(){stopped++;}}]})};
   context.window.AudioContext=class{constructor(){this.sampleRate=sampleRate;this.destination={};}createMediaStreamSource(){return {connect(){},disconnect(){}};}createScriptProcessor(){return {connect(){},disconnect(){}};}createGain(){return {gain:{},connect(){},disconnect(){}};}resume(){return Promise.resolve();}close(){return Promise.resolve();}};
   run("let submissions=0;wav=async()=> 'fixture-wav';sendTurn=async()=>{submissions++}");
   const block=(amplitude,frames=4096)=>{context.samples=new Float32Array(frames).fill(amplitude);run('state.mic.processor.onaudioprocess({inputBuffer:{getChannelData:()=>samples}})');};
   for(const rate of [16000,44100,48000]){sampleRate=rate;await run('toggleMic()');for(let i=0;i<6;i++)block(.0079);assert(run('!!state.mic'),'initial silence/noise submitted');
     for(let i=0;i<Math.ceil(.2*rate/4096);i++)block(.0081);
     for(let i=0;i<Math.floor(.4*rate/4096);i++)block(0);assert(run('!!state.mic'),'400 ms pause submitted');block(.009);
     const blocks=Math.ceil(.65*rate/4096);for(let i=0;i<blocks-1;i++)block(0);assert(run('!!state.mic'),'endpoint ignored frame quantization');
     const timer=[...timers.values()].find(t=>t.delay===15000);block(0);timer.fn();await run('toggleMic()');await flush();assert.equal(run('submissions'),[16000,44100,48000].indexOf(rate)+1,'endpoint/manual/timer submitted more than once');run('stopMic()');
   }
   let permissionResolve;context.navigator.mediaDevices.getUserMedia=()=>new Promise(r=>{permissionResolve=r;});const opening=run('toggleMic()');await flush();await run('endDemo()');permissionResolve({getTracks:()=>[{stop(){stopped++;}}]});await opening;assert.equal(run('state.mic'),null,'failed end revived pending microphone');
   context.navigator.mediaDevices.getUserMedia=async()=>({getTracks:()=>[{stop(){}}]});sampleRate=16000;await run('toggleMic()');block(.05);
   let encodeResolve;context.encodePending=new Promise(r=>{encodeResolve=r;});run('wav=()=>encodePending');const encoding=run('toggleMic()');await flush();await run('endDemo()');encodeResolve('fixture');await encoding;assert.equal(run('submissions'),3,'failed end revived encoding');
   await run('toggleMic()');const lateTimer=[...timers.values()].find(t=>t.delay===15000);run('logout()');lateTimer.fn();await flush();assert.equal(run('submissions'),3,'logout timer sent stale audio');
 }
 if(group==='bounds'){
   connected();context.largeAudio=Buffer.alloc(8*1024*1024).toString('base64');let error=null, bytes=null;
   try {bytes=run('audioBytes(largeAudio)');}catch(e){error=e.message;}
   assert.equal(error,null,'bounded maximum-size base64 overflowed the validator');assert.equal(bytes.length,8*1024*1024);
   context.tooLarge=Buffer.alloc(8*1024*1024+1).toString('base64');assert.throws(()=>run('audioBytes(tooLarge)'));
   await streamTurn([reply,chunk,{...done,tts_failed:true,recap_delivery_id:null}]);assert.equal(run('state.awaitingRecapId'),null);assert(el('demo-status').textContent.includes('Speech synthesis') || el('demo-status').textContent.includes('Audio'),'canonical provider failure was lost');
   const huge={...chunk,audio_b64:Buffer.alloc(128*1024+1).toString('base64')};await streamTurn([reply,huge,done]);assert.equal(run('state.audioUrl'),null,'oversized chunk accepted');
   const many=Array.from({length:257},(_,seq)=>({type:'audio',seq,audio_b64:Buffer.alloc(32768).toString('base64')}));await streamTurn([reply,...many,done]);assert.equal(run('state.awaitingRecapId'),null,'over-8MiB audio accepted');
 }
 if(group==='lifecycle'){
   connected();let endResolve, deletes=0;const originalFetch=context.fetch;
   context.fetch=async(path,opts)=>{if(opts?.method==='DELETE'){deletes++;return new Promise(resolve=>{endResolve=resolve;});}return originalFetch(path,opts);};
   const ending=run('endDemo()');await flush();run('endDemo()');await flush();assert.equal(deletes,1,'duplicate end request was not serialized');
   run("state.sessionId='new-session';state.demoEpoch++;state.turnBusy=false;state.demoEnding=false");endResolve(json({}));await ending;
   assert.equal(run('state.sessionId'),'new-session','stale end response cleared a newer session');
 }
 console.log('modern_voice_'+group+'_ok');
}
checks().catch(e=>{console.error(e);process.exitCode=1;});
"""
