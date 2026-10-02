"use strict";
const $ = id => document.getElementById(id);
const state = {credential:"", connected:false, generation:0, controllers:new Set(), bookings:[], fetchedAt:null, hasMore:false, page:1, readBusy:false, retryAt:0, failures:0, view:0, highlightId:null, sessionId:null, turnBusy:false, audioUrl:null, mic:null};
// Retire the old sessionStorage stopgap; never persist a new credential.
try { sessionStorage.removeItem("voicebot.operatorToken"); localStorage.removeItem("voicebot.operatorToken"); } catch (_) {}

function tallinnDay() {
  const parts = new Intl.DateTimeFormat("en", {timeZone:"Europe/Tallinn", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date());
  const get = key => parts.find(part => part.type === key).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
const query = new URLSearchParams(location.search);
$("booking-date").value = /^\d{4}-\d{2}-\d{2}$/.test(query.get("date") || "") ? query.get("date") : tallinnDay();
state.page = Math.max(1, Math.min(100, Number(query.get("page")) || 1));

function status(id, text, kind="") { $(id).textContent = text; $(id).className = "status " + kind; }
function stopAudio() {
  $("demo-audio").pause(); $("demo-audio").removeAttribute("src"); $("demo-audio").load(); $("demo-audio").hidden = true;
  if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
  state.audioUrl = null;
}
function stopMic() {
  const mic = state.mic; state.mic = null;
  if (!mic) return null;
  clearTimeout(mic.timer);
  mic.stream.getTracks().forEach(track => track.stop());
  mic.processor.disconnect(); mic.source.disconnect(); mic.gain.disconnect();
  mic.context.close().catch(() => {});
  $("demo-mic").textContent = "Luba mikrofon ja räägi";
  return mic;
}
function controls() {
  $("logout").disabled = !state.connected;
  $("connect").disabled = !!state.credential;
  $("refresh").disabled = !state.connected || state.readBusy;
  $("demo-start").disabled = !state.connected || !!state.sessionId || state.turnBusy;
  $("demo-end").disabled = !state.sessionId || state.turnBusy;
  for (const id of ["demo-text", "demo-send", "demo-mic"]) $(id).disabled = !state.sessionId || state.turnBusy;
  $("booking-prev").disabled = !state.connected || state.readBusy || state.page <= 1;
  $("booking-next").disabled = !state.connected || state.readBusy || !state.hasMore || state.page >= 100;
}
function logout(message="Ühendus lõpetatud. Privaatseid andmeid enam ei kuvata.") {
  state.generation++;
  state.controllers.forEach(controller => controller.abort()); state.controllers.clear();
  stopMic(); stopAudio();
  Object.assign(state, {credential:"", connected:false, bookings:[], fetchedAt:null, hasMore:false, readBusy:false, retryAt:0, failures:0, highlightId:null, sessionId:null, turnBusy:false});
  $("token").value = ""; $("demo-text").value = "";
  document.querySelector("#bookings tbody").replaceChildren();
  for (const id of ["calls", "catalogue", "demo-messages"]) $(id).replaceChildren();
  $("booking-empty").hidden = true;
  status("auth-status", message);
  status("booking-status", "Andmed on privaatsed. Ühenda esmalt.");
  status("catalogue-status", "Ühenda teenuste vaatamiseks.");
  status("calls-status", "Ühenda päeviku vaatamiseks.");
  status("demo-status", "Ühenda esmalt. Vestlus aegub 10 minutiga.");
  controls();
}
async function api(path, opts={}) {
  const isPrivate = path !== "/api/status";
  if (isPrivate && !state.credential) throw new DOMException("Signed out", "AbortError");
  const generation = state.generation;
  const controller = new AbortController();
  if (isPrivate) state.controllers.add(controller);
  const headers = new Headers(opts.headers || {});
  if (isPrivate) headers.set("Authorization", "Bearer " + state.credential);
  try {
    const response = await fetch(path, {...opts, headers, signal:controller.signal, cache:"no-store"});
    if (isPrivate && generation !== state.generation) throw new DOMException("Signed out", "AbortError");
    if (!response.ok) {
      const error = new Error(response.status === 403 || response.status === 401 ? "Tunnus puudub või on vale. Ühenda uuesti." : response.status === 410 ? "Vestlus aegus. Alusta uut vestlust; ära korda ebaselget broneerimist." : response.status === 409 ? "Vestlus töötleb eelmist sõnumit. Oota vastus ära." : response.status === 413 ? "Sõnum või helisalvestis on liiga pikk. Tee lühem proov." : response.status === 400 ? "Kontrolli kuupäeva või sõnumi vormingut." : "Teenus ei ole praegu saadaval. Kontrolli seadistust või proovi hiljem uuesti.");
      error.status = response.status;
      if (isPrivate && (response.status === 403 || response.status === 401)) logout(error.message);
      throw error;
    }
    const data = await response.json();
    if (isPrivate && generation !== state.generation) throw new DOMException("Signed out", "AbortError");
    return data;
  } finally { state.controllers.delete(controller); }
}
async function connect() {
  const credential = $("token").value.trim();
  logout("Kontrollin operaatori tunnust…");
  if (!credential) { status("auth-status", "Sisesta operaatori tunnus.", "error"); return; }
  state.credential = credential; controls();
  const generation=state.generation;
  try {
    const data = await api("/api/calls");
    if(generation!==state.generation || !state.credential) return;
    state.connected = true; $("token").value = "";
    renderCalls(data.calls || []); status("auth-status", "Operaator ühendatud. Tunnus on ainult lehe mälus."); controls();
    await Promise.allSettled([loadBookings(true), loadCatalogue(), loadStatus()]);
  } catch (error) {
    if (error.name !== "AbortError") logout(error.message);
  }
}
function renderBookings() {
  const tbody = document.querySelector("#bookings tbody"); tbody.replaceChildren();
  const warnings = {ambiguous:"Korduv kohalik aeg (DST) — täpne hetk pole määratud", invalid:"Olematu kohalik aeg (DST) — vajab kontrolli", unknown_timezone:"Ajavöönd pole kinnitatud"};
  for (const item of state.bookings) {
    const row = document.createElement("tr");
    row.dataset.bookingId=String(item.id);
    if(String(item.id)===state.highlightId) row.className="highlight";
    const cells = [["Teenus", item.service_name], ["Teenindaja", item.provider_name], ["Algus ja lõpp", `${item.start_local} – ${item.end_local}`], ["Ajavöönd", item.timezone || "Kinnitamata"], ["Taustsüsteemi olek", item.status], ["Viide", String(item.id)]];
    cells.forEach(([label, text], index) => {
      const cell = document.createElement("td"); cell.dataset.label = label;
      const value = document.createElement("span"); value.textContent = text; cell.append(value);
      if (index === 3 && warnings[item.time_state]) { const warning = document.createElement("span"); warning.className="sub"; warning.textContent=warnings[item.time_state]; cell.append(warning); }
      row.append(cell);
    }); tbody.append(row);
  }
  $("booking-page").textContent = `Leht ${state.page} · kuni 50 kirjet`;
  $("booking-empty").hidden = !state.fetchedAt || state.bookings.length > 0;
  controls();
}
async function loadBookings(force=false) {
  if (!state.connected || state.readBusy || (!force && Date.now() < state.retryAt)) return;
  const generation = state.generation, view = state.view;
  const params = new URLSearchParams({date:$("booking-date").value, page:String(state.page), length:"50"});
  state.readBusy = true; controls(); status("booking-status", "Laadin taustsüsteemi broneeringuid…");
  try {
    const data = await api("/api/bookings?" + params);
    if (generation !== state.generation || !state.connected || view !== state.view) return;
    Object.assign(state, {bookings:data.items || [], fetchedAt:data.fetched_at, hasMore:data.has_more === "unknown", failures:0, retryAt:0});
    renderBookings(); status("booking-status", `Taustsüsteemist kontrollitud. Viimane edukas laadimine: ${data.fetched_at}`);
  } catch (error) {
    if (error.name === "AbortError" || generation !== state.generation || view !== state.view) return;
    state.hasMore = false;
    state.retryAt = Date.now() + Math.min(120000, 30000 * 2 ** state.failures++);
    status("booking-status", (state.fetchedAt ? `Aegunud andmed. Viimane edukas laadimine: ${state.fetchedAt}. ` : "Broneeringuid ei õnnestunud kontrollida. ") + error.message, state.fetchedAt ? "stale" : "error");
    $("booking-empty").hidden = true;
  } finally {
    if (generation === state.generation) { state.readBusy=false; controls(); if (view !== state.view) await loadBookings(true); }
  }
}
async function loadCatalogue() {
  if (!state.connected) return;
  const generation=state.generation;
  try {
    const data = await api("/api/catalogue");
    if(generation!==state.generation || !state.connected) return;
    $("catalogue").replaceChildren();
    for (const service of data.services || []) {
      const item=document.createElement("li"); item.textContent=`${service.name} · ${service.duration} min`;
      const providers=(data.providers || []).filter(p => p.services.includes(service.id)).map(p => p.name);
      const note=document.createElement("span"); note.className="sub"; note.textContent=providers.join(", ") || "Teenindaja vajab kontrolli"; item.append(note); $("catalogue").append(item);
    }
    status("catalogue-status", data.services.length ? "Teenused taustsüsteemist; hindu ei kuvata." : "Taustsüsteemis pole teenuseid.");
  } catch (error) { if (error.name !== "AbortError" && state.connected) { $("catalogue").replaceChildren(); status("catalogue-status", error.message, "error"); } }
}
function renderCalls(calls) {
  $("calls").replaceChildren();
  for (const call of calls) {
    const item=document.createElement("li"); item.textContent=`${call.at} · ${call.lang} · ${call.outcome}${call.source === "demo" ? " · näidis" : ""}`; $("calls").append(item);
  }
  status("calls-status", calls.length ? "Toimingute tehnilised tulemused. Näidiskirjed on eraldi märgitud." : "Toiminguid pole.");
}
async function loadCalls() { if (state.connected) { const generation=state.generation; try { const data=await api("/api/calls"); if(generation!==state.generation || !state.connected) return; renderCalls(data.calls || []); } catch(error) { if(error.name!=="AbortError" && state.connected) status("calls-status", "Päevik on aegunud. " + error.message, "stale"); } } }
async function loadStatus(path="/api/status") {
  try {
    const data=await api(path), cap=data.capabilities || {}, telephone=data.telephone || {};
    $("livekit").textContent = telephone.media_credentials_configured ? "Meedia: seadistus olemas, ühendus pole siin kontrollitud" : "Meedia: seadistamata";
    $("telephone").textContent = telephone.public_ingress_verified && telephone.carrier_call_verified ? "Telefonikõne: tõendatud" : "Telefonikõne: kinnitamata";
    $("mode").textContent = cap.text_turn_ready ? "HTTP kõneproov: kõnepakkujad seadistatud" : "HTTP kõneproov: kõnepakkujad seadistamata";
  } catch (_) { $("mode").textContent="HTTP kõneproov: olek kontrollimata"; }
}
function addMessage(label, text) { const item=document.createElement("li"), author=document.createElement("strong"), content=document.createElement("span"); author.textContent=label; content.textContent=text; item.append(author,content); $("demo-messages").append(item); }
async function startDemo() {
  if (!state.connected || state.turnBusy || state.sessionId) return;
  state.turnBusy=true; controls();
  const generation=state.generation;
  try { const data=await api("/api/demo/session", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"}); if(generation!==state.generation || !state.connected) return; state.sessionId=data.session_id; $("demo-messages").replaceChildren(); addMessage("Demoabiline", data.greeting); status("demo-status", "Fiktiivne vestlus alustatud. Saadavus ja kirjutused kontrollitakse taustsüsteemist."); }
  catch(error) { if(error.name!=="AbortError" && state.connected) status("demo-status", error.message, "error"); }
  finally { if(generation===state.generation) { state.turnBusy=false; controls(); } }
}
async function sendTurn(input) {
  if (!state.sessionId || state.turnBusy || !state.connected) return;
  const generation=state.generation;
  state.turnBusy=true; controls(); stopAudio(); status("demo-status", "Demoabiline vastab… Ära saada sama kinnitust uuesti.");
  try {
    const data=await api("/api/turn", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({session_id:state.sessionId, language:"et", ...input})});
    if(generation!==state.generation || !state.connected) return;
    addMessage("Sina", data.text_heard || "Heli ei tuvastatud"); addMessage("Demoabiline", data.reply);
    $("demo-text").value="";
    const outcome={ok:"Vastus valmis.", tools_ok:"Taustsüsteemi tööriistad vastasid.", tools_failed:"Mõni toiming ebaõnnestus — edu ei ole kinnitatud.", unknown_outcome:"Kirjutuse tulemus on ebaselge. Ära korda broneerimist; kontrolli taustsüsteemi.", fallback:"Kasutati varuvastust.", tts_failed:"Kõnesüntees ebaõnnestus; tekst on alles."};
    status("demo-status", (outcome[data.outcome] || "Vastus valmis.") + (data.tts_failed ? " Heli pole saadaval; loe vastust tekstina." : "") + ` Voor ${data.turn_count || 1}; vestlus aegub ${data.expires_in_s || 0} s pärast.`, ["tools_failed","unknown_outcome","tts_failed"].includes(data.outcome) ? "error" : "");
    if (data.audio_b64) {
      const bytes=Uint8Array.from(atob(data.audio_b64), c=>c.charCodeAt(0));
      state.audioUrl=URL.createObjectURL(new Blob([bytes], {type:data.audio_type === "audio/wav" ? "audio/wav" : "audio/mpeg"}));
      $("demo-audio").src=state.audioUrl; $("demo-audio").hidden=false; $("demo-audio").play().catch(()=>{});
    }
    const change=(data.booking_changes || []).find(item=>["confirmed","cancelled"].includes(item.action) && /^\d{4}-\d{2}-\d{2}$/.test(item.date) && /^[1-9]\d*$/.test(item.id));
    if(change) { $("booking-date").value=change.date; await changeView(1,change.action==="confirmed" ? change.id : null); }
    else await loadBookings(true);
    await loadCalls();
  } catch(error) {
    if(error.name!=="AbortError" && state.connected) { status("demo-status", error.message + " Toimingut ei korrata automaatselt. Ebaselge tulemuse korral kontrolli broneeringute tabelit.", "error"); if(error.status===410 || error.status===404) state.sessionId=null; }
  } finally { if(generation===state.generation) { state.turnBusy=false; controls(); } }
}
async function endDemo() {
  if(!state.sessionId || state.turnBusy) return;
  stopMic(); stopAudio();
  const id=state.sessionId, generation=state.generation; state.turnBusy=true; controls();
  try { await api("/api/demo/session/"+encodeURIComponent(id), {method:"DELETE"}); if(generation!==state.generation || !state.connected) return; state.sessionId=null; $("demo-messages").replaceChildren(); status("demo-status", "Vestlus lõpetatud. Broneeringuid see automaatselt ei tühista."); }
  catch(error) { if(error.name!=="AbortError" && state.connected) status("demo-status", error.message,"error"); }
  finally { if(generation===state.generation) { state.turnBusy=false; controls(); } }
}
function wav(mic) {
  const count=mic.chunks.reduce((sum,c)=>sum+c.length,0), input=new Float32Array(count); let at=0;
  for(const chunk of mic.chunks) { input.set(chunk,at); at+=chunk.length; }
  const rate=16000, frames=Math.min(240000, Math.floor(count*rate/mic.context.sampleRate)), buffer=new ArrayBuffer(44+frames*2), view=new DataView(buffer);
  const text=(offset,s)=>{for(let i=0;i<s.length;i++)view.setUint8(offset+i,s.charCodeAt(i));};
  text(0,"RIFF"); view.setUint32(4,36+frames*2,true); text(8,"WAVE"); text(12,"fmt "); view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true); view.setUint32(24,rate,true); view.setUint32(28,rate*2,true); view.setUint16(32,2,true); view.setUint16(34,16,true); text(36,"data"); view.setUint32(40,frames*2,true);
  for(let i=0;i<frames;i++) { const sample=Math.max(-1,Math.min(1,input[Math.floor(i*mic.context.sampleRate/rate)] || 0)); view.setInt16(44+i*2,sample<0?sample*32768:sample*32767,true); }
  const bytes=new Uint8Array(buffer); let binary=""; for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192)); return btoa(binary);
}
async function toggleMic() {
  if(state.mic) { const mic=stopMic(); await sendTurn({audio_b64:wav(mic)}); return; }
  if(!state.sessionId || state.turnBusy) return;
  const generation=state.generation, session=state.sessionId;
  let stream=null, context=null;
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:true});
    if(generation!==state.generation || session!==state.sessionId || state.mic || state.turnBusy) { stream.getTracks().forEach(track=>track.stop()); return; }
    context=new (window.AudioContext || window.webkitAudioContext)();
    const source=context.createMediaStreamSource(stream), processor=context.createScriptProcessor(4096,1,1), gain=context.createGain(); gain.gain.value=0;
    const mic={stream,context,source,processor,gain,chunks:[],frames:0}; state.mic=mic;
    processor.onaudioprocess=event=>{if(state.mic!==mic)return; const chunk=event.inputBuffer.getChannelData(0); const remaining=Math.max(0,Math.floor(context.sampleRate*15)-mic.frames); mic.chunks.push(new Float32Array(chunk.subarray(0,remaining))); mic.frames+=Math.min(chunk.length,remaining); if(!remaining) toggleMic();};
    source.connect(processor); processor.connect(gain); gain.connect(context.destination); await context.resume();
    if(generation!==state.generation || state.mic!==mic) return;
    mic.timer=setTimeout(()=>{if(state.mic===mic)toggleMic();},15000);
    $("demo-mic").textContent="Lõpeta ja saada heli"; status("demo-status", "Mikrofon salvestab kuni 15 sekundit. Lõpetamiseks vajuta uuesti.");
  } catch(_) {
    if(state.mic?.stream===stream) stopMic();
    else { stream?.getTracks().forEach(track=>track.stop()); context?.close().catch(()=>{}); }
    if(generation===state.generation) status("demo-status", "Mikrofon ei avanenud. Luba brauseris mikrofon või saada tekstsõnum.","error");
  }
}
async function changeView(page=1, highlightId=null) {
  state.view++; state.page=page; state.highlightId=highlightId; state.bookings=[]; state.fetchedAt=null; state.hasMore=false; renderBookings();
  const url=new URL(location.href); url.searchParams.set("date",$("booking-date").value); url.searchParams.set("page",String(page)); history.replaceState(null,"",url);
  await loadBookings(true);
}
async function poll() { if(document.hidden) return; await loadStatus(); if(state.connected) await Promise.allSettled([loadBookings(),loadCalls()]); }
$("auth-form").addEventListener("submit", event=>{event.preventDefault(); connect();});
$("logout").addEventListener("click",()=>logout());
$("refresh").addEventListener("click",()=>Promise.allSettled([loadBookings(true),loadCatalogue(),loadCalls(),loadStatus()]));
$("booking-date").addEventListener("change",()=>changeView());
$("booking-prev").addEventListener("click",()=>{if(state.page>1)changeView(state.page-1);});
$("booking-next").addEventListener("click",()=>{if(state.hasMore && state.page<100)changeView(state.page+1);});
$("demo-start").addEventListener("click",startDemo); $("demo-end").addEventListener("click",endDemo);
$("demo-form").addEventListener("submit", event=>{event.preventDefault(); const text=$("demo-text").value.trim(); if(text) { stopMic(); sendTurn({text}); }});
$("demo-mic").addEventListener("click",toggleMic);
window.addEventListener?.("pagehide",()=>logout());
document.addEventListener("visibilitychange",()=>{if(document.hidden)stopMic(); else poll();});
controls();
