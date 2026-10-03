// Real Chromium, local fixture HTTP endpoints and generated WAV only. No providers.
// node tests/dashboard_delivery_checks.cjs /absolute/path/to/playwright [case filter] [published]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.argv[2] || 'playwright');
const root = path.resolve(__dirname, '../app/dashboard/static');
const published=process.argv[4]==='published';
const asset=name=>published ? execFileSync('git',['show',`origin/master:app/dashboard/static/${name}`],{cwd:path.resolve(__dirname,'..')}) : fs.readFileSync(path.join(root,name));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const tone = Buffer.alloc(44 + 16000 * 2 * 2);
tone.write('RIFF'); tone.writeUInt32LE(tone.length - 8, 4); tone.write('WAVEfmt ', 8);
tone.writeUInt32LE(16, 16); tone.writeUInt16LE(1, 20); tone.writeUInt16LE(1, 22);
tone.writeUInt32LE(16000, 24); tone.writeUInt32LE(32000, 28);
tone.writeUInt16LE(2, 32); tone.writeUInt16LE(16, 34); tone.write('data', 36);
tone.writeUInt32LE(tone.length - 44, 40);
for (let i = 44; i < tone.length; i += 2) tone.writeInt16LE(Math.round(Math.sin((i - 44) / 2 * Math.PI / 40) * 1200), i);
const mp3=fs.readFileSync(path.join(__dirname,'fixtures/speech-tone.mp3'));
const id3=mp3.subarray(0,3).toString()==='ID3' ? 10+((mp3[6]&127)<<21)+((mp3[7]&127)<<14)+((mp3[8]&127)<<7)+(mp3[9]&127) : 0;
const streamTone=Buffer.concat([mp3,...Array(7).fill(mp3.subarray(id3))]);

const cases = [];
const test = (name, run) => cases.push({name, run});
async function ready(page) {
  await page.goto(origin);
  await page.waitForLoadState('networkidle');
  await page.locator('#token').fill('fixture-operator');
  await page.locator('#connect').click();
  await page.waitForFunction(() => state.connected && bookingUi.tables.length && !state.readBusy && !historyState.busy);
}
async function start(page) {
  await page.locator('#demo-start').click();
  await page.waitForFunction(() => !!state.sessionId && !state.turnBusy);
}
async function send(page, text = 'Fiktiivne küsimus') {
  await page.locator('#demo-text').fill(text);
  await page.locator('#demo-send').click();
  await page.waitForFunction(() => !state.turnBusy);
}
async function prepare(page) {
  await page.locator('#booking-search').click();
  await page.waitForFunction(() => !bookingUi.busy && document.querySelector('.offer-button'));
  await page.locator('.offer-button').click();
  await page.waitForFunction(() => !bookingUi.busy && !document.getElementById('booking-recap').hidden);
}
const hasReceipt = input => Object.hasOwn(input, 'recap_delivery_id');

test('direct recap rendering cannot acknowledge or confirm', async (page, f) => {
  await prepare(page);
  assert.equal(f.posts('/api/booking/recap').length, 0, 'rendering silently acknowledged the recap');
  assert(await page.locator('#booking-confirm').isDisabled(), 'rendering opened consent before reading');
  const read = page.locator('#booking-recap-read');
  assert(await read.isEnabled(), 'deliberate read action unavailable');
  await read.focus(); await page.keyboard.press('Enter');
  await page.waitForFunction(() => !bookingUi.busy);
  assert.equal(f.posts('/api/booking/recap').length, 1);
  assert.deepEqual(f.posts('/api/booking/recap')[0], {session_id:'fixture-booking',hold_id:'fixture-hold',recap_delivery_id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'});
  assert.equal(f.posts('/api/booking/confirm').length, 0, 'reading also confirmed a booking');
  assert(await page.locator('#booking-confirm').isEnabled());
  assert(await page.locator('#booking-confirm').evaluate(button=>button===document.activeElement), 'reading did not leave keyboard focus on the separate confirmation');
  await page.locator('#booking-confirm').click();
  await page.waitForFunction(() => !bookingUi.busy);
  assert.equal(f.posts('/api/booking/confirm').length, 1);
  assert.equal(f.posts('/api/booking/confirm')[0].consent, true);
  assert((await page.locator('#booking-receipt-text').textContent()).includes('table_'+'a'.repeat(32)));
});

test('a late direct recap acknowledgement cannot restore signed-out controls', async (page, f) => {
  await prepare(page);
  f.stallRecap=true;
  await page.locator('#booking-recap-read').click();
  await page.waitForFunction(()=>bookingUi.busy);
  for(let i=0;i<100 && !f.releaseRecap;i++) await sleep(10);
  assert.equal(typeof f.releaseRecap, 'function', 'deliberate reading did not send acknowledgement');
  await page.locator('#logout').click();
  f.releaseRecap(); await sleep(100);
  assert(await page.locator('#booking-recap').isHidden(), 'late acknowledgement restored private recap');
  assert(await page.locator('#booking-confirm').isDisabled(), 'late acknowledgement restored signed-out consent');
  assert.equal(f.posts('/api/booking/confirm').length, 0);
});

test('recap reading actions fit narrow layouts and remain keyboard-accessible', async (page, f) => {
  await prepare(page); await start(page); await send(page);
  fs.mkdirSync(path.resolve(__dirname,'../output/playwright'),{recursive:true});
  for(const width of [1440,1024,768,700,390,320]) {
    await page.setViewportSize({width,height:900});
    const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert(size.scroll<=size.width, 'recap action overflow at '+width+': '+size.scroll);
    for(const id of ['booking-recap-read','demo-recap-read']) {
      const button=page.locator('#'+id);
      assert(await button.isVisible() && await button.isEnabled(), id+' unavailable at '+width);
      const bounds=await button.boundingBox();
      assert(bounds.x>=0 && bounds.x+bounds.width<=width+.1, id+' extends outside viewport at '+width);
    }
    if([1440,390,320].includes(width)) {
      await page.locator('#demo-recap-read').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.resolve(__dirname,`../output/playwright/recap-read-${width}.png`)});
    }
  }
  await page.locator('#demo-recap-read').focus(); await page.keyboard.press('Enter');
  await send(page, 'Jah, kinnitan.');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id, '11112222333344445555666677778888');
});

test('unread voice recap is not attached to the next input', async (page, f) => {
  await start(page); await send(page);
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'rendering acknowledged the voice recap');
});

test('an empty recap reply cannot be acknowledged', async (page, f) => {
  f.emptyReply=true;
  await start(page); await send(page);
  assert(await page.locator('#demo-recap-read').isHidden(), 'empty recap opened the reading action');
  await page.evaluate(() => document.getElementById('demo-recap-read').click());
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'empty recap was acknowledged');
});

test('a malformed recap receipt never opens reading or consent', async (page, f) => {
  f.receiptId='not-a-scoped-receipt';
  await start(page); await send(page);
  assert(await page.locator('#demo-recap-read').isHidden(), 'malformed receipt opened the reading action');
  await page.evaluate(() => document.getElementById('demo-recap-read').click());
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'malformed receipt was attached');
});

for(const outcome of ['fallback','tools_failed','unknown_outcome']) {
  test(outcome+' reply cannot authorize recap delivery', async (page, f) => {
    f.outcome=outcome; f.audio=true;
    await start(page); await send(page);
    await page.waitForFunction(() => document.getElementById('demo-audio').ended);
    assert.equal(await page.evaluate(()=>state.recapDeliveryId), null, 'failed or fallback reply was acknowledged by playback');
    assert(await page.locator('#demo-recap-read').isHidden(), 'failed or fallback reply opened the reading action');
    await page.evaluate(() => document.getElementById('demo-recap-read').click());
    await send(page, 'Jah, kinnitan.');
    assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'failed or fallback reply attached a receipt');
  });
}

test('explicit voice reading attaches a one-use receipt without a write', async (page, f) => {
  await start(page); await send(page);
  const postsBeforeReading=f.requests.filter(request=>request.method==='POST').length;
  const read = page.getByRole('button', {name:'Olen kokkuvõtte läbi lugenud',exact:true});
  assert(await read.isVisible(), 'voice recap has no explicit read action');
  assert(await read.getAttribute('aria-describedby'), 'read action lacks context');
  await read.focus(); await page.keyboard.press('Enter');
  assert.equal(f.posts('/api/turn').length, 1, 'reading unexpectedly sent a turn or write');
  assert.equal(f.requests.filter(request=>request.method==='POST').length, postsBeforeReading, 'reading used a redundant acknowledgement request');
  assert(await page.locator('#demo-text').evaluate(input=>input===document.activeElement), 'hiding the read action lost keyboard focus');
  await send(page, 'Jah, kinnitan.');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id, '11112222333344445555666677778888');
  await send(page, 'Veel üks küsimus');
  assert.equal(hasReceipt(f.posts('/api/turn')[2]), false, 'consumed receipt replayed');
});

test('full native playback attaches the receipt to the next input', async (page, f) => {
  f.audio = true;
  await start(page); await send(page);
  await page.waitForFunction(() => document.getElementById('demo-audio').ended);
  const played = await page.locator('#demo-audio').evaluate(a => ({duration:a.duration,ranges:Array.from({length:a.played.length},(_,i)=>[a.played.start(i),a.played.end(i)])}));
  assert(played.ranges.length && played.ranges[0][0] < .001 && played.ranges.at(-1)[1] >= played.duration - .001, 'fixture did not fully play');
  assert.equal(f.requests.filter(request=>request.method==='POST').length, 2, 'playback sent an automatic acknowledgement request');
  await send(page, 'Jah, kinnitan.');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id, '11112222333344445555666677778888', 'complete playback was not acknowledged');
});

test('a delivered receipt survives native microphone capture for the next input', async (page, f) => {
  await start(page); await send(page);
  await page.locator('#demo-recap-read').click();
  await page.evaluate(async () => {
    const context=new AudioContext(),source=context.createOscillator(),destination=context.createMediaStreamDestination();
    source.frequency.value=440; source.connect(destination); source.start(); await context.resume();
    window.fixtureCapture={context,source,stream:destination.stream};
    navigator.mediaDevices.getUserMedia=async()=>destination.stream;
  });
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>state.mic?.frames>=8192);
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!state.micStarting && !state.turnBusy);
  assert.equal(f.posts('/api/turn').length, 2, 'capture sent more than one input');
  assert(f.posts('/api/turn')[1].audio_b64, 'capture failed to upload actual audio');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id, '11112222333344445555666677778888', 'capture erased the delivered receipt');
  assert(await page.evaluate(()=>fixtureCapture.stream.getTracks().every(track=>track.readyState==='ended')), 'capture retained microphone tracks');
  await page.evaluate(async()=>{fixtureCapture.source.stop();await fixtureCapture.context.close();});
});

test('microphone barge-in cannot transfer a partially played receipt', async (page, f) => {
  f.audio=true;
  await start(page); await send(page);
  await page.waitForFunction(() => document.getElementById('demo-audio').currentTime > .1);
  await page.evaluate(async () => {
    const context=new AudioContext(),source=context.createOscillator(),destination=context.createMediaStreamDestination();
    source.frequency.value=440; source.connect(destination); source.start(); await context.resume();
    window.fixtureCapture={context,source,stream:destination.stream};
    navigator.mediaDevices.getUserMedia=async()=>destination.stream;
    window.partialEnded=document.getElementById('demo-audio').onended;
  });
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>state.mic?.frames>=8192);
  await page.evaluate(()=>partialEnded?.());
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!state.micStarting && !state.turnBusy);
  assert.equal(f.posts('/api/turn').length, 2, 'barge-in sent more than one input');
  assert(f.posts('/api/turn')[1].audio_b64, 'barge-in did not send captured audio');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'barge-in acknowledged partial playback');
  assert(await page.evaluate(()=>fixtureCapture.stream.getTracks().every(track=>track.readyState==='ended')), 'barge-in retained microphone tracks');
  await page.evaluate(async()=>{fixtureCapture.source.stop();await fixtureCapture.context.close();});
});

test('seek-to-end is not recap delivery', async (page, f) => {
  f.audio = true;
  await page.evaluate(() => {window.nativePlay=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(){return Promise.reject(new DOMException('Fixture autoplay blocked','NotAllowedError'));};});
  await start(page); await send(page);
  await page.waitForFunction(() => document.getElementById('demo-audio').readyState >= 2);
  await page.locator('#demo-audio').evaluate(async a => {a.currentTime=a.duration-.08;await new Promise(resolve=>a.addEventListener('seeked',resolve,{once:true}));await nativePlay.call(a);});
  await page.waitForFunction(() => document.getElementById('demo-audio').ended);
  const firstPlayed = await page.locator('#demo-audio').evaluate(a => a.played.start(0));
  assert(firstPlayed > 1, 'fixture did not skip the recap');
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'skipped recap was acknowledged');
});

test('interrupted playback and stale ended callbacks cannot acknowledge', async (page, f) => {
  f.audio = true;
  await start(page); await send(page);
  await page.waitForFunction(() => document.getElementById('demo-audio').currentTime > .1);
  await page.evaluate(() => {window.oldEnded=document.getElementById('demo-audio').onended;stopAudio();});
  await send(page, 'Muudan valikut');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'interrupted recap was acknowledged');
  await page.evaluate(() => {oldEnded?.(new Event('ended'));document.getElementById('demo-audio').dispatchEvent(new Event('ended'));});
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[2]), false, 'stale media callback revived a receipt');
});

test('paused partial playback does not become delivery when resumed', async (page, f) => {
  f.audio = true;
  await start(page); await send(page);
  await page.waitForFunction(() => document.getElementById('demo-audio').currentTime > .1);
  await page.locator('#demo-audio').evaluate(a => a.pause());
  await sleep(30);
  await page.locator('#demo-audio').evaluate(a => a.play());
  await page.waitForFunction(() => document.getElementById('demo-audio').ended);
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'interrupted playback incorrectly acknowledged');
});

test('autoplay rejection does not acknowledge and leaves reading available', async (page, f) => {
  f.audio = true;
  await page.evaluate(() => {HTMLMediaElement.prototype.play=function(){return Promise.reject(new DOMException('Fixture autoplay blocked','NotAllowedError'));};});
  await start(page); await send(page);
  assert(await page.locator('#demo-recap-read').isVisible(), 'blocked audio left no safe reading path');
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'blocked playback acknowledged the recap');
});

test('superseding an unread recap removes the old reading action', async (page, f) => {
  await start(page); await send(page);
  assert(await page.locator('#demo-recap-read').isVisible(), 'recap reading action is missing');
  await send(page, 'Muudan valikut');
  assert(await page.locator('#demo-recap-read').isHidden(), 'superseded recap remained acknowledgeable');
  await page.evaluate(() => document.getElementById('demo-recap-read').click());
  await send(page, 'Jah, kinnitan.');
  assert(f.posts('/api/turn').every(input => !hasReceipt(input)), 'superseded receipt revived');
});

test('expired receipt is not attached even after explicit reading', async (page, f) => {
  f.expires = 1;
  await start(page); await send(page);
  assert(await page.locator('#demo-recap-read').isVisible());
  await page.locator('#demo-recap-read').click();
  await sleep(1100);
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'expired receipt was attached');
});

test('preparation expiry removes a receipt while the session remains alive', async (page, f) => {
  f.expires=600; f.recapExpires=1;
  await start(page); await send(page);
  await page.locator('#demo-recap-read').click();
  await sleep(1100);
  await send(page, 'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'expired preparation retained the session-length receipt');
});

test('server-rejected stale receipt explains recap recovery without retrying consent', async (page, f) => {
  await start(page); await send(page);
  await page.locator('#demo-recap-read').click();
  f.rejectReceipt=true;
  await send(page, 'Jah, kinnitan.');
  const message=await page.locator('#demo-status').textContent();
  assert(message.includes('kokkuvõte') && message.includes('aegus'), 'stale recap receipt is mislabeled as an in-progress turn');
  assert(!message.includes('eelmist sõnumit'), 'stale receipt told the user to wait for a nonexistent turn');
  assert.equal(f.posts('/api/turn').length, 2, 'receipt rejection retried consent');
  f.rejectReceipt=false;
  await send(page, 'Küsin uut kokkuvõtet');
  assert.equal(hasReceipt(f.posts('/api/turn')[2]), false, 'rejected receipt replayed');
});

test('logout and session end discard delivered receipts', async (page, f) => {
  await start(page); await send(page);
  assert(await page.locator('#demo-recap-read').isVisible());
  await page.locator('#demo-recap-read').click();
  await page.locator('#logout').click(); await ready(page); await start(page); await send(page);
  assert.equal(hasReceipt(f.posts('/api/turn')[1]), false, 'logout retained a receipt');
  f.turns=0; await send(page);
  await page.locator('#demo-recap-read').click();
  await page.locator('#demo-end').click();
  await page.waitForFunction(() => !state.sessionId && !state.turnBusy);
  await start(page); await send(page);
  assert.equal(hasReceipt(f.posts('/api/turn').at(-1)), false, 'session end retained a receipt');
});

test('successful turn controls do not wait for stalled reads', async (page, f) => {
  await start(page);
  f.stallReads = true;
  await page.locator('#demo-text').fill('Fiktiivne küsimus');
  await page.locator('#demo-send').click();
  await page.waitForFunction(() => document.querySelectorAll('#demo-messages li').length===3);
  await sleep(100);
  assert(await page.locator('#demo-send').isEnabled(), 'finished turn waits for an unrelated read');
  assert(await page.locator('#demo-mic').isEnabled());
  assert(await page.locator('#demo-end').isEnabled());
  assert.equal(f.posts('/api/turn').length, 1, 'stalled read retried the write');
  assert(f.requests.some(r => r.url.pathname==='/api/table-bookings' && r.stalled), 'schedule fixture did not stall');
  assert(f.requests.some(r => r.url.pathname==='/api/call-history' && r.stalled), 'history fixture did not run independently');
});

test('session start and end controls do not wait for history reads', async (page, f) => {
  f.stallReads=true;
  await page.locator('#demo-start').click();
  await page.waitForFunction(() => !!state.sessionId);
  await sleep(100);
  assert(await page.locator('#demo-send').isEnabled(), 'start waits for history');
  await page.locator('#demo-end').click();
  await page.waitForFunction(() => !state.sessionId);
  await sleep(100);
  assert(await page.locator('#demo-start').isEnabled(), 'end waits for history');
});

test('completed direct booking does not wait for schedule reads', async (page, f) => {
  await prepare(page);
  if (await page.locator('#booking-recap-read').count()) await page.locator('#booking-recap-read').click();
  else assert(await page.locator('#booking-confirm').isEnabled(), 'baseline recap did not complete');
  await page.waitForFunction(() => !bookingUi.busy);
  f.stallReads=true;
  await page.locator('#booking-confirm').click();
  await page.waitForFunction(() => !document.getElementById('booking-receipt').hidden);
  await sleep(100);
  assert(await page.locator('#booking-cancel-request').isEnabled(), 'completed booking waits for schedule');
  assert.equal(f.posts('/api/booking/confirm').length, 1);
});

test('read deadlines recover stale rows without repeating a write', async (page, f) => {
  await start(page);
  await page.evaluate(() => {const original=window.setTimeout;window.setTimeout=(fn,delay,...args)=>original(fn,delay===30000?250:delay,...args);});
  f.stallReads=true;
  await page.locator('#demo-text').fill('Fiktiivne küsimus');
  await page.locator('#demo-send').click();
  await page.waitForFunction(() => document.querySelectorAll('#demo-messages li').length===3);
  await page.waitForFunction(() => !state.readBusy && !bookingUi.staysBusy && !historyState.busy);
  assert((await page.locator('#booking-status').textContent()).includes('ooteaeg'));
  assert.equal(await page.locator('#bookings tbody tr').count(), 1, 'deadline erased stale rows');
  assert.equal(f.posts('/api/turn').length, 1, 'read timeout retried a write');
  assert(await page.locator('#demo-send').isEnabled());
});

test('failed write is never automatically retried or given a reused receipt', async (page, f) => {
  await start(page); await send(page);
  assert(await page.locator('#demo-recap-read').isVisible());
  await page.locator('#demo-recap-read').click();
  f.failTurn=true;
  await send(page, 'Jah, kinnitan.'); await sleep(100);
  assert.equal(f.posts('/api/turn').length, 2, 'uncertain write was automatically repeated');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id, '11112222333344445555666677778888');
  assert((await page.locator('#demo-status').textContent()).includes('ei korrata automaatselt'));
  f.failTurn=false;
  await send(page, 'Kontrollin olekut');
  assert.equal(hasReceipt(f.posts('/api/turn')[2]), false, 'failed write retained a consumed receipt');
});

test('English reading is localized and still requires a separate one-use confirmation', async (page, f) => {
  await page.locator('#demo-language').selectOption('en');
  await start(page); await send(page, 'A fictional booking');
  assert.equal(f.posts('/api/demo/session')[0].language, 'en');
  assert.equal(await page.locator('#demo-messages .assistant-message').last().getAttribute('lang'), 'en');
  assert.equal(await page.locator('#demo-recap-help').count(), 1, 'English reading help is missing');
  assert((await page.locator('#demo-recap-help').textContent()).includes('beginning to end'), 'English reading help is missing');
  const postsBeforeReading=f.requests.filter(request=>request.method==='POST').length;
  const read=page.getByRole('button', {name:'I have read the recap',exact:true});
  assert(await read.getAttribute('aria-describedby'), 'English read action lacks context');
  await read.focus(); await page.keyboard.press('Enter');
  const message=await page.locator('#demo-status').textContent();
  assert(message.includes('read') && message.includes('No booking') && message.includes('Yes, I confirm.'), 'English reading status lost the separate-confirmation boundary');
  assert.equal(f.requests.filter(request=>request.method==='POST').length, postsBeforeReading, 'English reading sent an acknowledgement or write');
  assert(await page.locator('#demo-text').evaluate(input=>input===document.activeElement), 'English reading lost keyboard focus');
  await send(page, 'Yes, I confirm.');
  assert.equal(f.posts('/api/turn')[1].language, 'en');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id, '11112222333344445555666677778888');
  await send(page, 'Check the result');
  assert.equal(hasReceipt(f.posts('/api/turn')[2]), false, 'English confirmation reused the receipt');
});

test('English stale receipt recovery is not mislabeled as a busy conversation', async (page, f) => {
  await page.locator('#demo-language').selectOption('en');
  await start(page); await send(page, 'A fictional booking');
  await page.locator('#demo-recap-read').click();
  f.rejectReceipt=true;
  await send(page, 'Yes, I confirm.');
  const message=await page.locator('#demo-status').textContent();
  assert(message.includes('recap') && message.includes('expired'), 'English stale receipt omitted recap recovery');
  assert(!message.includes('previous message'), 'English stale receipt was mislabeled as a busy conversation');
  assert.equal(f.posts('/api/turn').length, 2, 'English receipt rejection retried consent');
  f.rejectReceipt=false;
  await send(page, 'Request a new recap');
  assert.equal(hasReceipt(f.posts('/api/turn')[2]), false, 'English rejected receipt replayed');
});

test('automatic language preserves Russian replies and the next-input receipt', async (page, f) => {
  f.replyLanguage='ru';
  await start(page); await send(page, 'Проверим предложение');
  assert.equal(f.posts('/api/demo/session')[0].language, 'auto', 'automatic greeting was pinned to Estonian');
  assert.equal(f.posts('/api/turn')[0].language, 'auto', 'automatic input was pinned to Estonian');
  assert.equal(await page.locator('#demo-messages .assistant-message').last().getAttribute('lang'), 'ru');
  const postsBeforeReading=f.requests.filter(request=>request.method==='POST').length;
  await page.locator('#demo-recap-read').click();
  assert((await page.locator('#demo-status').textContent()).includes('Да, подтверждаю.'), 'auto mode lost the Russian confirmation phrase');
  assert.equal(f.requests.filter(request=>request.method==='POST').length, postsBeforeReading, 'Russian reading sent an acknowledgement or write');
  await send(page, 'Да, подтверждаю.');
  assert.equal(f.posts('/api/turn')[1].language, 'auto');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id, '11112222333344445555666677778888');
});

test('published English browser contract passes against pure local fixtures', async (page, f) => {
  f.english=true;
  page.setDefaultTimeout(8000);
  const check=eval('('+fs.readFileSync(path.join(__dirname,'english_demo_browser_checks.js'),'utf8').replaceAll('http://127.0.0.1:8765',origin)+')');
  const result=await check(page);
  assert.equal(result.result, 'passed');
  console.log(JSON.stringify({check:'english_demo_browser_checks.js',fixture:'pure-local',...result}));
});

test('MSE complete native playback attaches exactly one next-input receipt', async (page, f) => {
  f.stream=true; f.gateStream=true;
  await start(page);
  await page.locator('#demo-text').fill('Fictional streamed recap'); await page.locator('#demo-send').click();
  await page.waitForFunction(()=>state.turnBusy && document.getElementById('demo-audio').currentTime>.08);
  assert(await page.evaluate(()=>state.playback.source instanceof MediaSource), 'fixture did not use native MSE');
  assert.equal(await page.evaluate(()=>state.recapDeliveryId), null, 'partial MSE output acknowledged the recap');
  assert(await page.locator('#demo-recap-read').isHidden(), 'partial MSE output opened reading before canonical done');
  assert.equal(typeof f.releaseStream, 'function'); f.releaseStream();
  await page.waitForFunction(()=>!state.turnBusy && document.getElementById('demo-audio').ended);
  const played=await page.evaluate(()=>{
    const audio=document.getElementById('demo-audio');
    return {duration:audio.duration,currentSrc:audio.currentSrc,url:state.audioUrl,source:state.playback.source.readyState,
      ranges:Array.from({length:audio.played.length},(_,i)=>[audio.played.start(i),audio.played.end(i)])};
  });
  assert.equal(played.source,'ended','MSE was not successfully closed');
  assert.equal(played.currentSrc,played.url,'MSE completion belongs to a different audio source');
  assert(played.ranges.length && played.ranges[0][0]<.001 && played.ranges.at(-1)[1]>=played.duration-.001,'native MSE did not cover the entire duration');
  assert(played.ranges.every((range,i)=>i===0 || range[0]<=played.ranges[i-1][1]+.001),'native MSE coverage has a gap');
  assert.equal(f.requests.filter(request=>request.method==='POST').length,2,'MSE completion sent an acknowledgement or booking request');
  await send(page,'Jah, kinnitan.');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id,'11112222333344445555666677778888','complete MSE playback was not acknowledged');
  await send(page,'Kontrollin olekut');
  assert.equal(hasReceipt(f.posts('/api/turn')[2]),false,'MSE receipt replayed');
});

test('MSE paused and resumed native playback cannot acknowledge', async (page, f) => {
  f.stream=true;
  await start(page); await send(page);
  await page.waitForFunction(()=>document.getElementById('demo-audio').currentTime>.08);
  await page.locator('#demo-audio').evaluate(a=>a.pause()); await sleep(50);
  await page.locator('#demo-audio').evaluate(a=>a.play());
  await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
  assert.equal(await page.evaluate(()=>state.recapDeliveryId),null,'resumed interrupted MSE was acknowledged');
  await send(page,'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]),false,'paused MSE attached a receipt');
});

test('MSE seeking skips delivery even if native playback reaches the end', async (page, f) => {
  f.stream=true;
  await start(page); await send(page);
  await page.waitForFunction(()=>document.getElementById('demo-audio').currentTime>.08 && Number.isFinite(document.getElementById('demo-audio').duration));
  await page.locator('#demo-audio').evaluate(a=>{a.currentTime=a.duration-.08;});
  await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
  await send(page,'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]),false,'seeked MSE attached a receipt');
});

test('MSE preparation expiry is not extended until HTTP EOF', async (page, f) => {
  f.stream=true; f.gateEOF=true; f.recapExpires=.2;
  await start(page);
  await page.locator('#demo-text').fill('Fictional streamed recap'); await page.locator('#demo-send').click();
  await page.waitForFunction(()=>document.getElementById('demo-audio').currentTime>.08);
  assert.equal(typeof f.releaseStream,'function');
  await sleep(350); f.releaseStream();
  await page.waitForFunction(()=>!state.turnBusy);
  assert(await page.locator('#demo-recap-read').isHidden(),'expired preparation opened reading after delayed EOF');
  await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
  await send(page,'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]),false,'expired MSE preparation used session TTL');
});

for(const outcome of ['fallback','tools_failed','unknown_outcome']) {
  test('MSE '+outcome+' cannot authorize recap delivery or reading', async (page, f) => {
    f.stream=true; f.outcome=outcome;
    await start(page); await send(page);
    await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
    assert.equal(await page.evaluate(()=>state.recapDeliveryId),null,'blocked MSE outcome was acknowledged');
    assert(await page.locator('#demo-recap-read').isHidden(),'blocked MSE outcome opened reading');
    await page.evaluate(()=>document.getElementById('demo-recap-read').click());
    await send(page,'Jah, kinnitan.');
    assert.equal(hasReceipt(f.posts('/api/turn')[1]),false,'blocked MSE outcome attached a receipt');
  });
}

test('MSE audio failure retains exact safe text for separate deliberate reading', async (page, f) => {
  f.stream=true; f.streamFailure='decode';
  await start(page); await send(page);
  await page.waitForFunction(()=>!state.audioUrl);
  assert.equal(await page.evaluate(()=>state.recapDeliveryId),null,'failed native decoding acknowledged audio');
  assert(await page.locator('#demo-recap-read').isVisible(),'failed audio discarded safe canonical text reading');
  const posts=f.requests.filter(request=>request.method==='POST').length;
  await page.locator('#demo-recap-read').click();
  assert.equal(f.requests.filter(request=>request.method==='POST').length,posts,'reading after decode failure sent an acknowledgement or write');
  await send(page,'Jah, kinnitan.');
  assert.equal(f.posts('/api/turn')[1].recap_delivery_id,'11112222333344445555666677778888','deliberate reading after failed audio was lost');
});

for(const failure of ['truncated','mismatch','synthesis']) {
  test('MSE '+failure+' stream cannot acknowledge or replay a receipt', async (page, f) => {
    f.stream=true; f.streamFailure=failure;
    await start(page); await send(page);
    await page.waitForFunction(()=>!state.audioUrl);
    assert.equal(await page.evaluate(()=>state.recapDeliveryId),null,'incomplete/failed stream acknowledged');
    assert(await page.locator('#demo-recap-read').isHidden(),'incomplete/failed stream opened reading');
    assert.equal(f.posts('/api/turn').length,1,'incomplete stream retried a POST');
    await page.evaluate(()=>document.getElementById('demo-audio').dispatchEvent(new Event('ended')));
    await send(page,'Jah, kinnitan.');
    assert.equal(hasReceipt(f.posts('/api/turn')[1]),false,'failed stream attached a receipt');
  });
}

test('MSE microphone barge-in retires partial audio and stale callbacks', async (page, f) => {
  f.stream=true;
  await start(page); await send(page);
  await page.waitForFunction(()=>document.getElementById('demo-audio').currentTime>.08);
  await page.evaluate(async()=>{
    const context=new AudioContext(),source=context.createOscillator(),sink=context.createMediaStreamDestination();
    source.connect(sink); source.start(); await context.resume();
    window.streamCapture={context,source,stream:sink.stream};
    navigator.mediaDevices.getUserMedia=async()=>sink.stream;
    window.streamEnded=document.getElementById('demo-audio').onended;
  });
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>state.mic?.frames>=8192);
  await page.evaluate(()=>streamEnded?.());
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!state.micStarting && !state.turnBusy);
  assert.equal(f.posts('/api/turn').length,2,'MSE barge-in sent duplicate inputs');
  assert(f.posts('/api/turn')[1].audio_b64,'MSE barge-in did not send real captured audio');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]),false,'MSE barge-in acknowledged partial audio');
  assert(await page.evaluate(()=>streamCapture.stream.getTracks().every(track=>track.readyState==='ended')),'MSE barge-in leaked microphone tracks');
  await page.evaluate(async()=>{streamCapture.source.stop();await streamCapture.context.close();});
});

test('MSE cancelled stream cannot revive a later session', async (page, f) => {
  f.stream=true; f.gateStream=true;
  await start(page);
  await page.locator('#demo-text').fill('Fictional streamed recap'); await page.locator('#demo-send').click();
  await page.waitForFunction(()=>state.turnBusy && document.getElementById('demo-audio').currentTime>.08);
  await page.evaluate(()=>{window.cancelledEnded=document.getElementById('demo-audio').onended;});
  await page.locator('#demo-end').click();
  await page.waitForFunction(()=>!state.sessionId && !state.turnBusy);
  f.releaseStream();
  await start(page); await page.evaluate(()=>cancelledEnded?.());
  await send(page,'Jah, kinnitan.');
  assert.equal(hasReceipt(f.posts('/api/turn')[1]),false,'cancelled stream revived an old session receipt');
  assert(await page.locator('#demo-recap-read').isHidden(),'cancelled stream restored old reading');
});

test('published modern voice contract passes against pure local fixtures', async (page) => {
  page.setDefaultTimeout(8000);
  const check=eval('('+fs.readFileSync(path.join(__dirname,'modern_voice_browser_checks.js'),'utf8').replaceAll('http://127.0.0.1:8765',origin)+')');
  const result=await check(page);
  assert.equal(result.result,'passed');
  console.log(JSON.stringify({check:'modern_voice_browser_checks.js',fixture:'pure-local',...result}));
});

for(const name of ['voice_browser_checks.js','microphone_race_browser_checks.js']) {
  test(name+' passes against pure local fixtures', async page=>{
    page.setDefaultTimeout(8000);
    const check=eval('('+fs.readFileSync(path.join(__dirname,name),'utf8').replaceAll('http://127.0.0.1:8765',origin)+')');
    const result=await check(page);
    assert.equal(result.result,'passed');
    console.log(JSON.stringify({check:name,fixture:'pure-local',...result}));
  });
}

test('published streaming UI contract passes against pure local HTTP chunks', async (page, f) => {
  f.stream=true; f.gateStream=true; f.streamingContract=true;
  page.setDefaultTimeout(8000);
  const check=eval('('+fs.readFileSync(path.join(__dirname,'streaming_voice_browser_checks.js'),'utf8').replaceAll('http://127.0.0.1:8776',origin)+')');
  const result=await check(page);
  assert.equal(result.result,'passed');
  console.log(JSON.stringify({check:'streaming_voice_browser_checks.js',fixture:'pure-local-not-production-backend',...result}));
});

let active, origin;
const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, origin);
  if (!url.pathname.startsWith('/api/') && !url.pathname.startsWith('/test/')) {
    const name = url.pathname==='/'?'index.html':url.pathname.slice(1);
    if (!/^[\w./-]+$/.test(name) || name.includes('..')) {response.writeHead(404).end();return;}
    try {
      const body=asset(name);
      response.writeHead(200, {'Content-Type':({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'})[path.extname(name)] || 'application/octet-stream'}).end(body);
    } catch (_) {response.writeHead(404).end();}
    return;
  }
  const f=active;
  let raw=''; for await (const chunk of request) raw+=chunk;
  const input=raw?JSON.parse(raw):null;
  const recorded={url,input,method:request.method,stalled:false}; f.requests.push(recorded);
  const reply=(body,status=200)=>response.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'}).end(JSON.stringify(body));
  if (url.pathname==='/api/status') return reply({wired:{},capabilities:{},models:{stt:{model:'fixture'},llm:{model:'fixture'},tts:{voice:'fixture'}},telephone:{english_voice:'en-US-JennyNeural'}});
  if (request.headers.authorization!=='Bearer fixture-operator') return reply({},403);
  if (f.stallReads && request.method==='GET' && ['/api/table-bookings','/api/calls','/api/call-history'].includes(url.pathname)) {recorded.stalled=true;return;}
  switch (url.pathname) {
    case '/test/stream/state': return reply({started:f.turns>0,completed:!!f.streamCompleted,writes:f.posts('/api/booking/confirm').length,records:f.posts('/api/booking/confirm').length});
    case '/test/stream/release': f.releaseStream?.(); return reply({released:true});
    case '/api/demo/voices': return reply({endpointing_ms:650,voices:[{id:'azure',label:'Azure',languages:['et','en','ru'],configured:true,available:true,streaming:true}]});
    case '/api/calls': return reply({calls:[]});
    case '/api/tables': return reply({tables:[{id:'table-01',name:'Laud 1',capacity:2}],rules:{timezone:'Europe/Tallinn',max_party_size:6}});
    case '/api/table-bookings': return reply({items:[{id:'table_'+'a'.repeat(32),table_name:'Laud 1',party_size:2,start_local:'2026-10-09 10:00:00',end_local:'2026-10-09 12:00:00',timezone:'Europe/Tallinn',time_state:'valid',status:'confirmed'}],fetched_at:'2026-10-03T10:00:00Z',has_more:false});
    case '/api/call-history': return reply({items:[],summary:{total:0,active:0,with_booking:0,needs_attention:0},fetched_at:'2026-10-03T10:00:00Z',has_more:false});
    case '/api/demo/session': {
      const language=input.language==='auto' ? f.replyLanguage || 'et' : input.language;
      return reply({session_id:'fixture-voice',language,greeting:language==='en'?'Hi! Fictional demo.':language==='ru'?'Здравствуйте! Тестовый разговор.':'Tere! Fiktiivne demo.',audio_b64:f.streamingContract?mp3.toString('base64'):f.english?tone.toString('base64'):'',audio_type:f.streamingContract?'audio/mpeg':'audio/wav',tts_failed:!f.english && !f.streamingContract});
    }
    case '/api/demo/session/fixture-voice': return reply({ok:true});
    case '/api/turn': {
      f.turns++;
      if (f.failTurn) return reply({detail:'write_outcome_unknown'},503);
      if (f.rejectReceipt && hasReceipt(input)) return reply({detail:'recap_delivery_expired_or_unknown'},409);
      const language=input.language==='auto' ? f.replyLanguage || 'et' : input.language;
      if(f.stream && f.turns===1) {
        const first={type:'reply',reply:'Fiktiivne broneeringu kokkuvõte. 9. oktoober kell 10. Kinnitamiseks anna järgmises sõnumis selge nõusolek.',language,audio_type:'audio/mpeg'};
        const done={...first,type:'done',text_heard:input.text || 'Fiktiivne heliproov',audio_b64:'',outcome:f.outcome || 'ok',tts_failed:false,booking_changes:[],turn_count:f.turns,expires_in_s:f.expires,recap_delivery_id:f.receiptId ?? '11112222333344445555666677778888',recap_expires_in_s:f.recapExpires ?? f.expires};
        if(f.streamFailure==='mismatch') done.reply='Different canonical recap.';
        if(f.streamFailure==='synthesis') {done.tts_failed=true;done.outcome='tts_failed';delete done.recap_delivery_id;delete done.recap_expires_in_s;}
        response.writeHead(200,{'Content-Type':'application/x-ndjson','Cache-Control':'no-store'});
        const write=event=>{if(!response.destroyed)response.write(JSON.stringify(event)+'\n');};
        const bytes=f.streamFailure==='decode'?Buffer.from('not-mp3'):streamTone;
        write(first);
        if(f.gateStream) {
          const split=Math.floor(bytes.length/2);
          write({type:'audio',seq:0,audio_b64:bytes.subarray(0,split).toString('base64')});
          f.releaseStream=()=>{f.streamCompleted=true;write({type:'audio',seq:1,audio_b64:bytes.subarray(split).toString('base64')});write(done);response.end();};
        } else {
          write({type:'audio',seq:0,audio_b64:bytes.toString('base64')});
          if(f.streamFailure!=='truncated') write(done);
          if(f.gateEOF) f.releaseStream=()=>response.end(); else response.end();
        }
        return;
      }
      if(f.english) return reply({text_heard:input.text || 'Fictional audio',language,reply:input.text==='Thank you'?"You're welcome. Fictional demo.":'Fictional reply.',outcome:'ok',audio_b64:'',booking_changes:[],expires_in_s:f.expires});
      return reply({text_heard:input.text || 'Fiktiivne heliproov',language,input_status:input.audio_b64?'recognized':'typed',reply:f.emptyReply?'':f.turns===1?'Fiktiivne broneeringu kokkuvõte. 9. oktoober kell 10. Kinnitamiseks anna järgmises sõnumis selge nõusolek.':'Fiktiivne vastus.',outcome:f.outcome || (f.audio&&f.turns===1?'ok':'tts_failed'),tts_failed:!f.audio || f.turns!==1,audio_b64:f.audio&&f.turns===1?tone.toString('base64'):'',audio_type:'audio/wav',recap_delivery_id:f.turns===1?(f.receiptId ?? '11112222333344445555666677778888'):undefined,turn_count:f.turns,expires_in_s:f.expires,recap_expires_in_s:f.recapExpires ?? f.expires,booking_changes:[]});
    }
    case '/api/booking/session': return reply({session_id:'fixture-booking'});
    case '/api/booking/search': return reply({kind:'table',offers:[{table_offer_id:'fixture-offer',table_id:'table-01',table_name:'Laud 1',capacity:2,party_size:2,start_time:'18:00',duration_minutes:120,date:'2026-10-09'}]});
    case '/api/booking/prepare': return reply({kind:'table',hold_id:'fixture-hold',recap_text:'Fiktiivne külaline. Laud 9. oktoobril kell 18.',recap_delivery_id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'});
    case '/api/booking/recap': if(f.stallRecap){f.releaseRecap=()=>reply({acknowledged:true,hold_id:'fixture-hold'});return;}return reply({acknowledged:true,hold_id:'fixture-hold'});
    case '/api/booking/confirm': return reply({ok:true,kind:'table',booking_id:'table_'+'a'.repeat(32),booking:{id:'table_'+'a'.repeat(32),date:'2026-10-09'}});
    default: return reply({},404);
  }
});

(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  origin=`http://127.0.0.1:${server.address().port}`;
  const browser=await chromium.launch({headless:true});
  let failed=0, passed=0;
  try {
    for (const {name,run} of cases.filter(c=>!process.argv[3] || c.name.includes(process.argv[3]))) {
      const f={requests:[],turns:0,audio:false,expires:590,stallReads:false,failTurn:false,posts(endpoint){return this.requests.filter(r=>r.url.pathname===endpoint && r.method==='POST').map(r=>r.input);}};
      active=f;
      const context=await browser.newContext({serviceWorkers:'block'});
      const external=[], errors=[];
      await context.route('**/*', route=>{const url=new URL(route.request().url());if(url.origin!==origin && url.protocol!=='blob:'){external.push(url.origin);return route.abort();}return route.continue();});
      const page=await context.newPage(); page.setDefaultTimeout(name.startsWith('MSE ')?8000:3500);
      page.on('pageerror',error=>errors.push(error.message));
      try {await ready(page);await run(page,f);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);passed++;console.log('PASS '+name);}
      catch(error) {failed++;console.error('FAIL '+name+': '+error.message);}
      finally {await context.close();server.closeAllConnections();}
    }
    console.log(JSON.stringify({passed,failed,chromium:browser.version(),assets:published?'origin/master':'working-tree',syntheticAudio:true,externalRequests:0}));
    if (failed) process.exitCode=1;
  } finally {await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error.message);process.exitCode=1;server.closeAllConnections();server.close();});
