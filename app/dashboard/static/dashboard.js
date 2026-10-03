"use strict";
const $ = id => document.getElementById(id);
const state = {credential:"", connected:false, generation:0, controllers:new Set(), bookings:[], fetchedAt:null, hasMore:false, page:1, readBusy:false, bookingError:false, retryAt:0, failures:0, view:0, highlightId:null, sessionId:null, callId:null, turnBusy:false, audioUrl:null, mic:null, micStarting:false};
const bookingUi = {kind:"slot", sessionId:null, busy:false, uncertain:false, holdId:null, acknowledged:false, selected:null, confirmed:null, services:[], providers:[], roomTypes:[], roomPresetApplied:false, stays:[], staysFetched:false, staysBusy:false, epoch:0};
// Retire the old sessionStorage stopgap; never persist a new credential.
try { sessionStorage.removeItem("voicebot.operatorToken"); localStorage.removeItem("voicebot.operatorToken"); } catch (_) {}

function tallinnDay() {
  const parts = new Intl.DateTimeFormat("en", {timeZone:"Europe/Tallinn", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date());
  const get = key => parts.find(part => part.type === key).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
const query = new URLSearchParams(location.search);
$("booking-date").value = /^\d{4}-\d{2}-\d{2}$/.test(query.get("date") || "") ? query.get("date") : tallinnDay();
// Native date inputs reject impossible calendar dates, not just bad formatting.
if (!$("booking-date").value) $("booking-date").value = tallinnDay();
const initialPage = Number(query.get("page"));
state.page = Number.isInteger(initialPage) && initialPage >= 1 && initialPage <= 100 ? initialPage : 1;

function status(id, text, kind="") { $(id).textContent = text; const component=id === "booking-status" ? "booking-status " : id === "history-status" ? "history-status " : ""; $(id).className = "status " + component + kind; }
function presentation() {
  $("connection-label").textContent = state.connected ? "Operaator ühendatud" : state.credential ? "Ühendan…" : "Ühendamata";
  $("connection-badge").className = "connection-badge" + (state.connected ? " connected" : "");
  $("auth-title").textContent = state.connected ? "Töölaud on ühendatud" : "Ühenda oma töölaud";
  $("auth-description").textContent = state.connected ? "Operaatori seanss on aktiivne." : "Broneeringute, teenuste ja kõneproovi avamiseks.";
  $("token-field").hidden = state.connected;
  $("token").disabled = state.connected;
  $("connect").hidden = state.connected;
  $("logout").hidden = !state.connected;
  $("auth-form").setAttribute("aria-busy", String(!!state.credential && !state.connected));
  $("booking-section").setAttribute("aria-busy", String(state.readBusy));
  $("demo-section").setAttribute("aria-busy", String(state.turnBusy));
  $("bookings").hidden = state.bookings.length === 0;
  $("booking-placeholder").hidden = state.connected && (!!state.fetchedAt || state.bookings.length > 0);
  $("booking-auth-link").hidden = state.connected;
  $("booking-placeholder-title").textContent = !state.connected ? "Sinu päeva broneeringud, ühes kohas" : state.bookingError ? "Broneeringuid ei saanud laadida" : "Kontrollin päeva broneeringuid…";
  $("booking-placeholder-copy").textContent = !state.connected ? "Ühenda operaatori tunnusega, et näha valitud päeva broneeringuid." : state.bookingError ? "Kontrolli ühendust ja vajuta „Uuenda andmeid”." : "Andmed tulevad otse broneerimissüsteemist.";
  $("catalogue-placeholder").hidden = state.connected;
  $("demo-placeholder").hidden = !!state.sessionId || $("demo-messages").children.length > 0;
  $("demo-mic").className = "button mic-button" + (state.mic ? " recording" : "");
  $("demo-mic").setAttribute("aria-pressed", String(!!state.mic));
  $("overview-slots").textContent = state.fetchedAt ? String(state.bookings.length) : "—";
  $("overview-stays").textContent = bookingUi.staysFetched ? String(bookingUi.stays.length) : "—";
  $("new-booking-section").setAttribute("aria-busy", String(bookingUi.busy));
  $("mic-feedback").hidden=!state.mic;
}
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
  presentation();
  return mic;
}
function controls() {
  $("logout").disabled = !state.connected;
  $("connect").disabled = !!state.credential;
  $("refresh").disabled = !state.connected || state.readBusy;
  $("demo-start").disabled = !state.connected || !!state.sessionId || state.turnBusy;
  $("demo-end").disabled = !state.sessionId || state.turnBusy;
  for (const id of ["demo-text", "demo-send", "demo-mic"]) $(id).disabled = !state.sessionId || state.turnBusy;
  $("demo-mic").disabled ||= state.micStarting;
  $("demo-history").hidden=!state.callId;
  $("demo-history").disabled=!state.connected;
  $("booking-prev").disabled = !state.connected || state.readBusy || state.page <= 1;
  $("booking-next").disabled = !state.connected || state.readBusy || !state.hasMore || state.page >= 100;
  bookingControls();
  for (const button of document.querySelectorAll?.(".example-button") || []) button.disabled = !state.sessionId || state.turnBusy;
  presentation();
  historyControls();
}
function logout(message="Ühendus lõpetatud. Privaatseid andmeid enam ei kuvata.", kind="") {
  state.generation++;
  state.controllers.forEach(controller => controller.abort()); state.controllers.clear();
  stopMic(); stopAudio();
  Object.assign(state, {credential:"", connected:false, bookings:[], fetchedAt:null, hasMore:false, readBusy:false, bookingError:false, retryAt:0, failures:0, highlightId:null, sessionId:null, callId:null, turnBusy:false, micStarting:false});
  resetBookingUi();
  $("token").value = ""; $("demo-text").value = "";
  $("demo-warning").hidden=true; $("demo-warning").textContent=""; $("demo-timings").hidden=true; $("demo-timings").textContent="";
  document.querySelector("#bookings tbody").replaceChildren();
  for (const id of ["calls", "catalogue", "demo-messages"]) $(id).replaceChildren();
  $("booking-empty").hidden = true;
  status("auth-status", message, kind);
  status("booking-status", "Andmed on privaatsed. Ühenda esmalt.");
  status("catalogue-status", "Ühenda teenuste vaatamiseks.");
  status("calls-status", "Ühenda päeviku vaatamiseks.");
  status("demo-status", "Ühenda esmalt. Vestlus aegub 10 minutiga.");
  resetHistory();
  controls();
}
async function api(path, opts={}) {
  const isPrivate = path !== "/api/status";
  if (isPrivate && !state.credential) throw new DOMException("Signed out", "AbortError");
  const generation = state.generation;
  const controller = new AbortController();
  let timedOut = false;
  const deadline = setTimeout(()=>{timedOut=true; controller.abort();}, path === "/api/turn" ? 120000 : 30000);
  if (isPrivate) state.controllers.add(controller);
  const headers = new Headers(opts.headers || {});
  if (isPrivate) headers.set("Authorization", "Bearer " + state.credential);
  try {
    const response = await fetch(path, {...opts, headers, signal:controller.signal, cache:"no-store"});
    if (isPrivate && generation !== state.generation) throw new DOMException("Signed out", "AbortError");
    if (!response.ok) {
      const problem=(await response.json().catch(()=>null)) || {};
      const explanations={booking_recap_expired_or_unknown:"Pakkumine aegus. Otsi saadavust uuesti ja vaata uus kokkuvõte üle.",booking_not_owned_or_cancellation_unavailable:"Seda broneeringut ei saa selles seansis tühistada. Kontrolli broneeringut operaatori taustsüsteemist.",explicit_consent_required:"Kinnitamiseks või tühistamiseks on vaja sinu selget nõusolekut.",booking_date_invalid:"Kuupäev ei sobi. Vali lubatud vahemikus tulevane kuupäev.",stay_booking_not_configured:"Tubade broneerimise taustsüsteem pole seadistatud.",voice_stack_not_configured:"Kõneproovi mudel või kõnesüntees pole serveris seadistatud.",mutation_outcome_unknown:"Broneerimise tulemus on ebaselge. Ära korda kinnitamist; kontrolli broneeringute ülevaadet.",write_outcome_unknown:"Broneerimise tulemus on ebaselge. Ära korda kinnitamist; kontrolli broneeringute ülevaadet.",cancel_outcome_unknown:"Tühistamise tulemus on ebaselge. Ära korda tühistamist; kontrolli broneeringute ülevaadet."};
      const message=explanations[problem.detail || problem.error] || (response.status === 403 || response.status === 401 ? "Tunnus puudub või on vale. Ühenda uuesti." : response.status === 410 ? "Vestlus aegus. Alusta uut vestlust; ära korda ebaselget broneerimist." : response.status === 409 ? (path.startsWith("/api/booking/")?"Pakkumine muutus, aegus või toiming ei ole selles seansis võimalik. Kontrolli valikut ja otsi saadavust uuesti.":"Vestlus töötleb eelmist sõnumit. Oota vastus ära.") : response.status === 413 ? "Sõnum või helisalvestis on liiga pikk. Tee lühem proov." : response.status === 400 ? "Kontrolli kuupäeva või sõnumi vormingut." : "Teenus ei ole praegu saadaval. Kontrolli seadistust või proovi hiljem uuesti.");
      const error = new Error(message);
      error.status = response.status;
      if (isPrivate && (response.status === 403 || response.status === 401)) logout(error.message, "error");
      throw error;
    }
    const data = await response.json();
    if (isPrivate && generation !== state.generation) throw new DOMException("Signed out", "AbortError");
    return data;
  } catch (error) {
    if (timedOut && generation === state.generation) throw new Error(path === "/api/turn" ? "Vastuse ooteaeg sai läbi. Tulemus võib olla ebaselge; ära korda kinnitust ega tühistust enne taustsüsteemi kontrolli." : "Ühenduse ooteaeg sai läbi. Kontrolli ühendust ja proovi hiljem uuesti.");
    throw error;
  } finally { clearTimeout(deadline); state.controllers.delete(controller); }
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
    renderCalls(data.calls || []); status("auth-status", "Operaator ühendatud. Tunnus on ainult lehe mälus.");
    status("new-booking-status",bookingUi.kind==="slot"?"Vali teenus ja kuupäev. Vabad ajad tulevad broneerimissüsteemist.":"Vali peatumise kuupäevad ja kontrolli demotubade saadavust.");
    status("demo-status", "Alusta demovestlust. Vestlus aegub 10 minutiga."); controls();
    await Promise.allSettled([loadBookings(true), loadCatalogue(), loadRooms(), loadHistory(), loadStays(), loadStatus()]);
  } catch (error) {
    if (error.name !== "AbortError") logout(error.message, "error");
  }
}
function localBookingRange(start, end) {
  // Format the provider's wall time directly; do not convert through device time.
  const pattern = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})(?::\d{2})?$/;
  const first = pattern.exec(start || ""), last = pattern.exec(end || "");
  if (!first || !last || start.slice(0, 10) !== end.slice(0, 10)) return {time:`${start} – ${end}`, date:""};
  return {time:`${first[4]} – ${last[4]}`, date:`${first[3]}.${first[2]}.${first[1]}`};
}
function renderBookings() {
  const tbody = document.querySelector("#bookings tbody"); tbody.replaceChildren();
  const warnings = {ambiguous:"Korduv kohalik aeg (DST) — täpne hetk pole määratud", invalid:"Olematu kohalik aeg (DST) — vajab kontrolli", unknown_timezone:"Ajavöönd pole kinnitatud"};
  for (const item of state.bookings) {
    const row = document.createElement("tr");
    row.dataset.bookingId=String(item.id);
    if(String(item.id)===state.highlightId) row.className="highlight";
    const range = localBookingRange(item.start_local, item.end_local);
    const cells = [["Teenus", item.service_name], ["Teenindaja", item.provider_name], ["Algus ja lõpp", range.time], ["Ajavöönd", item.timezone || "Kinnitamata"], ["Taustsüsteemi olek", item.status], ["Viide", String(item.id)]];
    cells.forEach(([label, text], index) => {
      const cell = document.createElement("td"); cell.dataset.label = label;
      const value = document.createElement("span"); value.textContent = text; cell.append(value);
      if (index === 4) value.className = "provider-status";
      if (index === 2 && range.date) { const date = document.createElement("span"); date.className="sub"; date.textContent=range.date; cell.append(date); }
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
  state.readBusy = true; state.bookingError = false; controls(); status("booking-status", "Laadin taustsüsteemi broneeringuid…");
  try {
    const data = await api("/api/bookings?" + params);
    if (generation !== state.generation || !state.connected || view !== state.view) return;
    Object.assign(state, {bookings:data.items || [], fetchedAt:data.fetched_at, hasMore:data.has_more === "unknown", failures:0, retryAt:0});
    renderBookings(); status("booking-status", `Taustsüsteemist kontrollitud. Uuendatud ${historyTime(data.fetched_at)}.`);
  } catch (error) {
    if (error.name === "AbortError" || generation !== state.generation || view !== state.view) return;
    state.hasMore = false;
    state.bookingError = true;
    state.retryAt = Date.now() + Math.min(120000, 30000 * 2 ** state.failures++);
    status("booking-status", (state.fetchedAt ? `Aegunud andmed. Viimane laadimine: ${historyTime(state.fetchedAt)}. ` : "Broneeringuid ei õnnestunud kontrollida. ") + error.message, state.fetchedAt ? "stale" : "error");
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
    bookingUi.services=data.services || []; bookingUi.providers=data.providers || [];
    fillSelect("new-service", bookingUi.services.map(item=>({value:String(item.id),label:item.name})), "Vali teenus");
    if(bookingUi.services.length===1) $("new-service").value=String(bookingUi.services[0].id);
    updateProviders(); bookingControls();
    $("catalogue").replaceChildren();
    for (const service of data.services || []) {
      const item=document.createElement("li"); item.textContent=`${service.name} · ${service.duration} min`;
      const providers=(data.providers || []).filter(p => p.services.includes(service.id)).map(p => p.name);
      const note=document.createElement("span"); note.className="sub"; note.textContent=providers.join(", ") || "Teenindaja vajab kontrolli"; item.append(note); $("catalogue").append(item);
    }
    status("catalogue-status", (data.services || []).length ? "Teenused taustsüsteemist; hindu ei kuvata." : "Taustsüsteemis pole teenuseid.");
  } catch (error) { if (error.name !== "AbortError" && state.connected) { $("catalogue").replaceChildren(); status("catalogue-status", error.message, "error"); } }
}
function renderCalls(calls) {
  $("calls").replaceChildren();
  for (const call of calls) {
    const item=document.createElement("li");
    for (const [text, className] of [[call.at, "call-time"], [call.lang, "call-language"], [call.outcome, "call-outcome"], [call.source === "demo" ? "Näidis" : "", "call-source"]]) {
      const value=document.createElement("span"); value.textContent=text; value.className=className; item.append(value);
    }
    $("calls").append(item);
  }
  status("calls-status", calls.length ? "Toimingute tehnilised tulemused. Näidiskirjed on eraldi märgitud." : "Toiminguid pole.");
}
async function loadLegacyCalls() { if (state.connected) { const generation=state.generation; try { const data=await api("/api/calls"); if(generation!==state.generation || !state.connected) return; renderCalls(data.calls || []); } catch(error) { if(error.name!=="AbortError" && state.connected) status("calls-status", "Päevik on aegunud. " + error.message, "stale"); } } }
async function loadCalls() { await Promise.allSettled([loadLegacyCalls(),loadHistory()]); }
async function loadStatus(path="/api/status") {
  try {
    const data=await api(path), cap=data.capabilities || {}, telephone=data.telephone || {};
    for (const [id,configured] of [["stack-stt",data.wired?.stt],["stack-llm",data.wired?.llm_primary],["stack-tts",data.wired?.tts],["stack-booking",cap.booking_read_ready]]) {
      $(id).textContent=configured === true ? "Seadistatud" : configured === false ? "Seadistus puudub" : "Kontrollimata";
      $(id).className=configured === true ? "configured" : configured === false ? "unconfigured" : "";
    }
    $("livekit").textContent = telephone.media_credentials_configured ? "Meedia: seadistus olemas, ühendus pole siin kontrollitud" : "Meedia: seadistamata";
    $("telephone").textContent = telephone.public_ingress_verified && telephone.carrier_call_verified ? "Telefonikõne: tõendatud" : "Telefonikõne: kinnitamata";
    $("mode").textContent = cap.text_turn_ready ? "HTTP kõneproov: kõnepakkujad seadistatud" : "HTTP kõneproov: kõnepakkujad seadistamata";
    $("overview-voice").textContent = cap.text_turn_ready ? "Proovi abilist" : "Seadistamata";
    const models=data.models || {};
    if(models.stt || models.llm || models.tts) $("demo-models").textContent=`Seadistatud: transkriptsioon ${models.stt?.model || "puudub"}; vastused ${models.llm?.model || "puudub"}; hääl ${models.tts?.voice || "puudub"}. Seadistus ei tõenda edukat telefonikõnet.`;
  } catch (_) { $("mode").textContent="HTTP kõneproov: olek kontrollimata"; $("overview-voice").textContent="Kontrollimata"; for(const id of ["stack-stt","stack-llm","stack-tts","stack-booking"]) { $(id).textContent="Kontrollimata"; $(id).className=""; } }
}
function addMessage(label, text) {
  const item=document.createElement("li"), author=document.createElement("strong"), content=document.createElement("span");
  item.className=label === "Sina" ? "user-message" : "assistant-message";
  author.textContent=label; content.textContent=text; item.append(author,content); $("demo-messages").append(item);
  $("demo-messages").scrollTop=$("demo-messages").scrollHeight;
}
async function startDemo() {
  if (!state.connected || state.turnBusy || state.sessionId) return;
  state.turnBusy=true; controls();
  const generation=state.generation;
  try { const data=await api("/api/demo/session", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"}); if(generation!==state.generation || !state.connected) return; state.sessionId=data.session_id; state.callId=/^[a-f0-9]{32}$/.test(data.call_id || "") ? data.call_id : null; $("demo-messages").replaceChildren(); addMessage("Demoabiline", data.greeting); status("demo-status", "Fiktiivne vestlus alustatud. Saadavus ja kirjutused kontrollitakse taustsüsteemist."); await loadHistory(); }
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
    addMessage("Sina", data.text_heard || (data.input_status === "stt_unavailable" ? "Kõnetuvastus ei olnud saadaval" : "Kõnet ei tuvastatud")); addMessage("Demoabiline", data.reply);
    renderTurnDiagnostics(data);
    $("demo-text").value="";
    const completedWrite=(data.booking_changes || []).some(change=>["confirmed","cancelled"].includes(change.action));
    const outcome={ok:"Vastus valmis.", tools_ok:"Taustsüsteemi tööriistad vastasid.", tools_failed:completedWrite?"Muu päring ebaõnnestus. Vaata vastust ja kontrolli taustsüsteemi.":"Mõni toiming ebaõnnestus — edu ei ole kinnitatud.", unknown_outcome:"Kirjutuse tulemus on ebaselge. Ära korda broneerimist; kontrolli taustsüsteemi.", fallback:"Kasutati varuvastust.", tts_failed:"Kõnesüntees ebaõnnestus; tekst on alles."};
    status("demo-status", (outcome[data.outcome] || "Vastus valmis.") + (data.tts_failed ? " Heli pole saadaval; loe vastust tekstina." : "") + ` Voor ${data.turn_count || 1}; vestlus aegub ${data.expires_in_s || 0} s pärast.`, ["tools_failed","unknown_outcome","tts_failed"].includes(data.outcome) ? "error" : "");
    if (data.input_status === "stt_unavailable") status("demo-status", "Kõnetuvastuse teenus ebaõnnestus. Proovi hetke pärast uuesti või kirjuta sõnum. Kõneajalugu sisaldab vea olekut.","error");
    else if (data.input_status === "no_speech") status("demo-status", "Kõnet ei tuvastatud. Kontrolli mikrofoni helitaset ja räägi pärast mikrofoni avanemist.","stale");
    if (data.audio_b64) {
      const bytes=Uint8Array.from(atob(data.audio_b64), c=>c.charCodeAt(0));
      state.audioUrl=URL.createObjectURL(new Blob([bytes], {type:data.audio_type === "audio/wav" ? "audio/wav" : "audio/mpeg"}));
      $("demo-audio").src=state.audioUrl; $("demo-audio").hidden=false; $("demo-audio").play().catch(()=>{});
    }
    const change=(data.booking_changes || []).find(item=>["confirmed","cancelled"].includes(item.action) && /^\d{4}-\d{2}-\d{2}$/.test(item.date) && (/^[1-9]\d*$/.test(item.id) || (item.kind==="stay" && /^stay_[a-f0-9]{32}$/.test(item.id))));
    if(change) { $("booking-date").value=change.date; await changeView(1,change.action==="confirmed" && change.kind!=="stay" ? change.id : null); }
    else await Promise.allSettled([loadBookings(true),loadStays()]);
    await loadCalls();
  } catch(error) {
    if(error.name!=="AbortError" && state.connected) { status("demo-status", error.message + " Toimingut ei korrata automaatselt. Ebaselge tulemuse korral kontrolli broneeringute tabelit.", "error"); if(error.status===410 || error.status===404) state.sessionId=null; }
  } finally { if(generation===state.generation) { state.turnBusy=false; controls(); } }
}
async function endDemo() {
  if(!state.sessionId || state.turnBusy) return;
  stopMic(); stopAudio();
  const id=state.sessionId, generation=state.generation; state.turnBusy=true; controls();
  try { await api("/api/demo/session/"+encodeURIComponent(id), {method:"DELETE"}); if(generation!==state.generation || !state.connected) return; state.sessionId=null; $("demo-messages").replaceChildren(); status("demo-status", "Vestlus lõpetatud. Broneeringuid see automaatselt ei tühista."); await loadHistory(); }
  catch(error) { if(error.name!=="AbortError" && state.connected) status("demo-status", error.message,"error"); }
  finally { if(generation===state.generation) { state.turnBusy=false; controls(); } }
}
function encodeWav(input, rate=16000) {
  const frames=Math.min(240000,input.length), buffer=new ArrayBuffer(44+frames*2), view=new DataView(buffer);
  const text=(offset,s)=>{for(let i=0;i<s.length;i++)view.setUint8(offset+i,s.charCodeAt(i));};
  text(0,"RIFF"); view.setUint32(4,36+frames*2,true); text(8,"WAVE"); text(12,"fmt "); view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true); view.setUint32(24,rate,true); view.setUint32(28,rate*2,true); view.setUint16(32,2,true); view.setUint16(34,16,true); text(36,"data"); view.setUint32(40,frames*2,true);
  for(let i=0;i<frames;i++) { const sample=Math.max(-1,Math.min(1,input[i] || 0)); view.setInt16(44+i*2,sample<0?sample*32768:sample*32767,true); }
  const bytes=new Uint8Array(buffer); let binary=""; for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192)); return btoa(binary);
}
async function wav(mic) {
  const count=mic.chunks.reduce((sum,c)=>sum+c.length,0), input=new Float32Array(count); let at=0;
  for(const chunk of mic.chunks) { input.set(chunk,at); at+=chunk.length; }
  if (mic.context.sampleRate === 16000) return encodeWav(input);
  // Let the browser resample with its audio filter; dropping every third
  // sample aliases higher frequencies into the speech band at 48 kHz.
  const frames=Math.min(240000, Math.floor(count*16000/mic.context.sampleRate));
  if (!frames) throw new Error("Mikrofonist ei saabunud heli. Proovi uuesti.");
  const Offline=window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const offline=new Offline(1,frames,16000), buffer=offline.createBuffer(1,count,mic.context.sampleRate);
  buffer.copyToChannel(input,0);
  const source=offline.createBufferSource(); source.buffer=buffer; source.connect(offline.destination); source.start();
  const rendered=await offline.startRendering(); return encodeWav(rendered.getChannelData(0));
}
async function toggleMic() {
  if(state.mic) {
    const mic=stopMic(), generation=state.generation, session=state.sessionId;
    if (!mic.frames || mic.peak < 0.00001) { status("demo-status", "Mikrofonist ei saabunud helisignaali. Kontrolli valitud mikrofoni ja proovi uuesti.","error"); return; }
    state.micStarting=true; controls();
    try { const audio=await wav(mic); if(generation===state.generation && session===state.sessionId && state.connected) await sendTurn({audio_b64:audio}); }
    catch(error) { if(generation===state.generation) status("demo-status", "Heliproovi ei saanud ette valmistada. " + error.message,"error"); }
    finally { if(generation===state.generation) { state.micStarting=false; controls(); } }
    return;
  }
  if(!state.sessionId || state.turnBusy || state.micStarting) return;
  const generation=state.generation, session=state.sessionId;
  let stream=null, context=null;
  state.micStarting=true; controls(); status("demo-status", "Ootan mikrofoni luba…");
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    if(generation!==state.generation || session!==state.sessionId || state.mic || state.turnBusy) { stream.getTracks().forEach(track=>track.stop()); return; }
    context=new (window.AudioContext || window.webkitAudioContext)();
    const source=context.createMediaStreamSource(stream), processor=context.createScriptProcessor(4096,1,1), gain=context.createGain(); gain.gain.value=0;
    const mic={stream,context,source,processor,gain,chunks:[],frames:0,peak:0}; state.mic=mic;
    processor.onaudioprocess=event=>{
      if(state.mic!==mic)return;
      const chunk=event.inputBuffer.getChannelData(0), remaining=Math.max(0,Math.floor(context.sampleRate*15)-mic.frames), kept=chunk.subarray(0,remaining);
      mic.chunks.push(new Float32Array(kept)); mic.frames+=kept.length;
      let energy=0; for(const sample of kept) { energy+=sample*sample; mic.peak=Math.max(mic.peak,Math.abs(sample)); }
      const level=Math.min(1,Math.sqrt(energy/Math.max(1,kept.length))*5); $("mic-level").value=level;
      $("mic-feedback-text").textContent=`${Math.floor(mic.frames/context.sampleRate)} / 15 s. ` + (level < .005 ? "Heli on vaikne. Kontrolli, kas valitud on õige mikrofon." : "Heli jõuab mikrofonist kohale. Lõpetamiseks vajuta uuesti.");
      if(mic.frames>=Math.floor(context.sampleRate*15)) toggleMic();
    };
    source.connect(processor); processor.connect(gain); gain.connect(context.destination); await context.resume();
    if(generation!==state.generation || state.mic!==mic) return;
    mic.timer=setTimeout(()=>{if(state.mic===mic)toggleMic();},15000);
    $("demo-mic").textContent="Lõpeta ja saada heli"; status("demo-status", "Mikrofon salvestab kuni 15 sekundit. Lõpetamiseks vajuta uuesti.");
    presentation();
  } catch(_) {
    if(state.mic?.stream===stream) stopMic();
    else { stream?.getTracks().forEach(track=>track.stop()); context?.close().catch(()=>{}); }
    if(generation===state.generation) status("demo-status", "Mikrofon ei avanenud. Luba brauseris mikrofon või saada tekstsõnum.","error");
  }
  finally { if(generation===state.generation) { state.micStarting=false; controls(); } }
}
async function changeView(page=1, highlightId=null) {
  state.view++; state.page=page; state.highlightId=highlightId; state.bookings=[]; state.fetchedAt=null; state.hasMore=false; state.bookingError=false; renderBookings();
  bookingUi.stays=[]; bookingUi.staysFetched=false; $("stays-list").replaceChildren(); presentation();
  if(state.connected) status("stays-status","Kontrollin valitud päeva peatumisi…");
  const url=new URL(location.href); url.searchParams.set("date",$("booking-date").value); url.searchParams.set("page",String(page)); history.replaceState(null,"",url);
  await Promise.allSettled([loadBookings(true),loadStays()]);
}
async function poll() { if(document.hidden) return; await loadStatus(); if(state.connected) await Promise.allSettled([loadBookings(),loadStays(),loadCalls()]); }
$("auth-form").addEventListener("submit", event=>{event.preventDefault(); connect();});
$("logout").addEventListener("click",()=>logout());
$("refresh").addEventListener("click",()=>Promise.allSettled([loadBookings(true),loadCatalogue(),loadStays(),loadRooms(),loadCalls(),loadStatus()]));
$("booking-date").addEventListener("change",()=>changeView());
$("booking-prev").addEventListener("click",()=>{if(state.page>1)changeView(state.page-1);});
$("booking-next").addEventListener("click",()=>{if(state.hasMore && state.page<100)changeView(state.page+1);});
$("demo-start").addEventListener("click",startDemo); $("demo-end").addEventListener("click",endDemo);
$("demo-form").addEventListener("submit", event=>{event.preventDefault(); const text=$("demo-text").value.trim(); if(text) { stopMic(); sendTurn({text}); }});
$("demo-mic").addEventListener("click",toggleMic);
$("demo-history").addEventListener("click",async()=>{const id=state.callId; if(!state.connected || !id)return; location.hash="calls-section"; await loadHistory(); if(state.connected) await selectHistory(id);});
window.addEventListener?.("pagehide",()=>logout());
document.addEventListener("visibilitychange",()=>{if(document.hidden)stopMic(); else poll();});
// Navigation stays useful without scripts; reflect the current anchor when available.
const navigation = Array.from(document.querySelectorAll?.(".navigation a") || []);
function updateNavigation() {
  const current = navigation.find(link => link.getAttribute("href") === location.hash) || navigation[0];
  for (const link of navigation) {
    if (link === current) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}
window.addEventListener?.("hashchange", updateNavigation);
updateNavigation();
$("booking-auth-link").addEventListener("click", event => { event.preventDefault(); $("token").focus(); });
$("today-label").textContent = new Intl.DateTimeFormat("et-EE", {timeZone:"Europe/Tallinn", day:"numeric", month:"long", year:"numeric"}).format(new Date());
$("today-label").setAttribute("datetime", tallinnDay());
initializeHistory();
controls();

function dayAfter(day, days=1) { return new Date(Date.parse(day+"T12:00:00Z")+days*86400000).toISOString().slice(0,10); }
function renderTurnDiagnostics(data) {
  const messages={transcription_unavailable:"Heli transkriptsioon ei ole praegu saadaval. Proovi tekstiga või kontrolli kõnetuvastuse seadistust.",reply_provider_unavailable:"Vastuse mudel ei vastanud. Kasutati varuvastust; kontrolli serveri mudeliseadistust.",reply_provider_fallback:"Vastuseks kasutati varumudelit.",reply_audio_unavailable:"Vastuse heli ei saanud luua. Vastus on tekstina alles; kontrolli kõnesünteesi seadistust."};
  const warnings=(data.warnings || []).map(item=>messages[item.code]).filter(Boolean);
  if(data.tts_failed && !warnings.some(item=>item===messages.reply_audio_unavailable)) warnings.push(messages.reply_audio_unavailable);
  $("demo-warning").textContent=warnings.join(" "); $("demo-warning").hidden=warnings.length===0;
  const timings=data.timings_ms || {}, labels={stt:"Kõnetuvastus",llm:"Vastus",tools:"Broneerimistööriistad",tts:"Kõnesüntees",total:"Kokku"};
  const values=Object.entries(labels).filter(([key])=>Number.isFinite(timings[key])).map(([key,label])=>`${label}: ${(timings[key]/1000).toFixed(1)} s`);
  $("demo-timings").textContent=values.join(" · "); $("demo-timings").hidden=values.length===0;
}
function fillSelect(id, items, placeholder) {
  const select=$(id), previous=select.value;
  select.replaceChildren();
  if(placeholder) { const option=document.createElement("option"); option.value=""; option.textContent=placeholder; select.append(option); }
  for(const item of items) { const option=document.createElement("option"); option.value=item.value; option.textContent=item.label; select.append(option); }
  select.value=items.some(item=>item.value===previous) ? previous : "";
}
function updateProviders() {
  const service=$("new-service").value;
  const providers=bookingUi.providers.filter(item=>(item.services || []).some(id=>String(id)===service));
  fillSelect("new-provider",providers.map(item=>({value:String(item.id),label:item.name})), "Vali teenindaja");
  if(providers.length===1) $("new-provider").value=String(providers[0].id);
}
function bookingControls() {
  const locked=!state.connected || bookingUi.busy;
  for(const id of ["new-service","new-provider","new-slot-date","new-checkin","new-checkout","new-adults","new-children","new-room-type","booking-kind-slot","booking-kind-stay","booking-decline","booking-cancel-request","booking-cancel-decline"]) $(id).disabled=locked;
  $("booking-search").disabled=locked || bookingUi.uncertain;
  $("booking-confirm").disabled=locked || bookingUi.uncertain || !bookingUi.holdId || !bookingUi.acknowledged;
  $("booking-cancel").disabled=locked || bookingUi.uncertain || !bookingUi.confirmed;
  for(const button of document.querySelectorAll?.(".offer-button") || []) button.disabled=locked || bookingUi.uncertain;
}
function resetBookingUi() {
  Object.assign(bookingUi,{sessionId:null,busy:false,uncertain:false,holdId:null,acknowledged:false,selected:null,confirmed:null,services:[],providers:[],roomTypes:[],roomPresetApplied:false,stays:[],staysFetched:false,staysBusy:false,epoch:bookingUi.epoch+1});
  for(const id of ["booking-offers","stays-list"]) $(id).replaceChildren();
  $("booking-recap").hidden=true; $("booking-receipt").hidden=true; $("booking-cancel-actions").hidden=true;
  $("booking-recap-text").textContent=""; $("booking-receipt-text").textContent="";
  fillSelect("new-service",[],"Ühenda teenuste laadimiseks"); fillSelect("new-provider",[],"Vali esmalt teenus"); fillSelect("new-room-type",[],"Kõik toatüübid");
  status("new-booking-status","Ühenda töölaud, et kontrollida saadavust ja teha testbroneering.");
  status("stays-status","Ühenda peatumiste vaatamiseks.");
}
function clearBookingSelection() {
  bookingUi.epoch++; bookingUi.holdId=null; bookingUi.acknowledged=false; bookingUi.selected=null;
  $("booking-offers").replaceChildren(); $("booking-recap").hidden=true;
  bookingControls();
}
function chooseBookingKind(kind) {
  if(bookingUi.busy) return;
  bookingUi.kind=kind; clearBookingSelection();
  for(const value of ["slot","stay"]) { const button=$("booking-kind-"+value); button.className="kind-button"+(kind===value?" active":""); button.setAttribute("aria-pressed",String(kind===value)); }
  $("slot-search-fields").hidden=kind!=="slot"; $("stay-search-fields").hidden=kind!=="stay";
  $("booking-search").textContent=kind==="slot"?"Leia vabad ajad →":"Leia vabad toad →";
  if(state.connected && !bookingUi.uncertain) status("new-booking-status",kind==="slot"?"Vali teenus ja kuupäev. Vabad ajad tulevad broneerimissüsteemist.":"Vali peatumise kuupäevad. Tubade arv ja näidishind kontrollitakse sünteetilisest taustsüsteemist.");
}
async function loadRooms() {
  if(!state.connected) return;
  const generation=state.generation;
  try {
    const data=await api("/api/rooms");
    if(generation!==state.generation || !state.connected) return;
    bookingUi.roomTypes=data.room_types || [];
    fillSelect("new-room-type",bookingUi.roomTypes.map(item=>({value:String(item.id),label:item.name})),"Kõik toatüübid");
    if(!bookingUi.roomPresetApplied && bookingUi.roomTypes.some(item=>String(item.id)===query.get("room"))) $("new-room-type").value=query.get("room");
    bookingUi.roomPresetApplied=true;
  } catch(error) { if(error.name!=="AbortError" && state.connected && bookingUi.kind==="stay") status("new-booking-status","Tubade loendit ei saanud laadida. "+error.message,"error"); }
}
async function loadStays() {
  if(!state.connected || bookingUi.staysBusy) return;
  const generation=state.generation, view=state.view;
  bookingUi.staysBusy=true;
  try {
    const data=await api("/api/stays?"+new URLSearchParams({date:$("booking-date").value}));
    if(generation!==state.generation || view!==state.view || !state.connected) return;
    bookingUi.stays=(data.items || []).filter(item=>item.status==="confirmed"); bookingUi.staysFetched=true;
    $("stays-list").replaceChildren();
    for(const item of bookingUi.stays) {
      const row=document.createElement("div"); row.className="stay-row";
      const content=document.createElement("div"), title=document.createElement("strong"), dates=document.createElement("span"), reference=document.createElement("span"), badge=document.createElement("span");
      title.textContent=item.room_name || item.room_type_id; dates.className="sub"; dates.textContent=`${item.checkin} → ${item.checkout} · ${item.nights} ööd · ${item.adults} täiskasvanut${item.children?" · "+item.children+" last":""}`;
      reference.className="sub"; reference.textContent="Viide: "+item.id; badge.className="provider-status"; badge.textContent=item.status==="confirmed"?"Kinnitatud":item.status;
      content.append(title,dates,reference); row.append(content,badge); $("stays-list").append(row);
    }
    status("stays-status",bookingUi.stays.length?"Peatumised sünteetilisest tubade taustsüsteemist.":"Valitud päeval sünteetilisi peatumisi ei ole.");
  } catch(error) { if(error.name!=="AbortError" && generation===state.generation && state.connected) status("stays-status",(bookingUi.staysFetched?"Aegunud andmed. ":"")+error.message,bookingUi.staysFetched?"stale":"error"); }
  finally { if(generation===state.generation) { bookingUi.staysBusy=false; presentation(); if(view!==state.view) await loadStays(); } }
}
function bookingRequestValid() {
  if(bookingUi.kind==="slot") return !!$("new-service").value && !!$("new-provider").value && /^\d{4}-\d{2}-\d{2}$/.test($("new-slot-date").value);
  const checkin=$("new-checkin").value, checkout=$("new-checkout").value, adults=Number($("new-adults").value), children=Number($("new-children").value);
  return /^\d{4}-\d{2}-\d{2}$/.test(checkin) && /^\d{4}-\d{2}-\d{2}$/.test(checkout) && checkout>checkin && Number.isInteger(adults) && adults>=1 && adults<=6 && Number.isInteger(children) && children>=0 && children<=4;
}
async function searchBooking() {
  if(!state.connected || bookingUi.busy || bookingUi.uncertain) return;
  if(!bookingRequestValid()) { status("new-booking-status",bookingUi.kind==="slot"?"Vali teenus, teenindaja ja kuupäev.":"Kontrolli kuupäevi ja külaliste arvu. Lahkumine peab olema pärast saabumist.","error"); return; }
  clearBookingSelection(); bookingUi.busy=true; controls();
  const generation=state.generation, epoch=bookingUi.epoch;
  status("new-booking-status","Kontrollin saadavust taustsüsteemist…");
  try {
    if(!bookingUi.sessionId) { const session=await api("/api/booking/session",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}); if(generation!==state.generation) return; bookingUi.sessionId=session.session_id; }
    const input=bookingUi.kind==="slot"?{service:$("new-service").value,provider:$("new-provider").value,date:$("new-slot-date").value}:{checkin:$("new-checkin").value,checkout:$("new-checkout").value,adults:Number($("new-adults").value),children:Number($("new-children").value),room_type:$("new-room-type").value || undefined};
    const data=await api("/api/booking/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:bookingUi.sessionId,kind:bookingUi.kind,...input})});
    if(generation!==state.generation || epoch!==bookingUi.epoch || !state.connected) return;
    const offers=bookingUi.kind==="slot"?(data.slots || []):(data.offers || []);
    for(const offer of offers) {
      const button=document.createElement("button"), title=document.createElement("strong"), note=document.createElement("span"); button.type="button"; button.className="offer-button";
      if(bookingUi.kind==="slot") { title.textContent=(offer.start || "").slice(11,16) || offer.start; note.textContent="Vali aeg ja vaata kokkuvõtet"; }
      else { title.textContent=offer.label || offer.room_name || offer.room_type_id; note.textContent=`${offer.nights} ööd · ${offer.quoted_total} ${offer.currency} näidishind · ${offer.available_rooms} vaba`; }
      button.append(title,note); button.addEventListener("click",()=>prepareBooking(offer)); $("booking-offers").append(button);
    }
    status("new-booking-status",offers.length?"Vali sobiv pakkumine. Broneering tekib pärast kokkuvõtte kinnitamist.":"Sellele valikule saadavust ei leitud. Proovi teist kuupäeva või külaliste arvu.");
  } catch(error) { if(error.name!=="AbortError" && generation===state.generation && state.connected) { status("new-booking-status",error.message,"error"); if(error.status===410 || error.status===404) bookingUi.sessionId=null; } }
  finally { if(generation===state.generation) { bookingUi.busy=false; controls(); } }
}
async function prepareBooking(offer) {
  if(!state.connected || bookingUi.busy || bookingUi.uncertain) return;
  bookingUi.busy=true; bookingUi.holdId=null; bookingUi.acknowledged=false; bookingUi.selected={...offer,kind:bookingUi.kind}; controls();
  const generation=state.generation, epoch=bookingUi.epoch;
  try {
    const selection=bookingUi.kind==="slot"?{slot_id:offer.slotId}:{price_quote_id:offer.price_quote_id};
    const data=await api("/api/booking/prepare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:bookingUi.sessionId,kind:bookingUi.kind,guest_fixture_id:"guest-001",...selection})});
    if(generation!==state.generation || epoch!==bookingUi.epoch || !state.connected) return;
    if(!data.hold_id || !data.recap_text) throw new Error("Broneeringu kokkuvõte puudub. Kinnitamist ei avatud.");
    bookingUi.holdId=data.hold_id; $("booking-recap-text").textContent=data.recap_text; $("booking-recap").hidden=false;
    if(window.requestAnimationFrame) await new Promise(resolve=>window.requestAnimationFrame(()=>window.requestAnimationFrame(resolve)));
    if(generation!==state.generation || epoch!==bookingUi.epoch || !state.connected) return;
    // Confirm is opened only after the canonical recap has entered the DOM.
    const acknowledgment=await api("/api/booking/recap",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:bookingUi.sessionId,hold_id:data.hold_id})});
    if(generation!==state.generation || epoch!==bookingUi.epoch || !state.connected) return;
    bookingUi.acknowledged=acknowledgment.acknowledged===true;
    status("new-booking-status",bookingUi.acknowledged?"Loe kokkuvõte läbi. Kinnitamiseks vajuta „Jah, kinnitan broneeringu”.":"Kokkuvõtet ei saanud kinnitamiseks avada. Broneeringut ei loodud.",bookingUi.acknowledged?"":"error");
  } catch(error) { if(error.name!=="AbortError" && generation===state.generation && state.connected) status("new-booking-status",error.message,"error"); }
  finally { if(generation===state.generation) { bookingUi.busy=false; controls(); } }
}
async function mutateBooking(action) {
  if(!state.connected || bookingUi.busy || bookingUi.uncertain || (action==="confirm" && (!bookingUi.holdId || !bookingUi.acknowledged)) || (action==="cancel" && !bookingUi.confirmed)) return;
  bookingUi.busy=true; controls();
  const generation=state.generation;
  status("new-booking-status",action==="confirm"?"Kinnitan testbroneeringut…":"Tühistan testbroneeringut…");
  try {
    const kind=action==="confirm"?bookingUi.kind:bookingUi.confirmed.kind;
    const selection=action==="confirm"?{hold_id:bookingUi.holdId}:{booking_id:bookingUi.confirmed.id};
    const data=await api("/api/booking/"+action,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:bookingUi.sessionId,kind,consent:true,...selection})});
    if(generation!==state.generation || !state.connected) return;
    if(data.outcome==="unknown_outcome" || data.unknown_outcome) { bookingUi.uncertain=true; throw new Error("Toimingu tulemus on ebaselge. Ära korda kinnitamist ega tühistamist. Kontrolli broneeringute ülevaadet."); }
    if(data.ok!==true) throw new Error("Taustsüsteem ei kinnitanud toimingu õnnestumist.");
    if(action==="confirm") {
      const receipt=data.booking || {}, id=String(data.booking_id || receipt.id || "");
      if(!id) { bookingUi.uncertain=true; throw new Error("Broneeringu viide puudub. Kontrolli taustsüsteemi enne uut toimingut."); }
      bookingUi.confirmed={kind,id}; bookingUi.holdId=null; bookingUi.acknowledged=false;
      $("booking-recap").hidden=true; $("booking-offers").replaceChildren(); $("booking-receipt").hidden=false; $("booking-cancel-request").hidden=false;
      $("booking-receipt-title").textContent="Testbroneering on kinnitatud"; $("booking-receipt-text").textContent="Taustsüsteemi viide: "+id;
      const day=kind==="stay"?(receipt.checkin || bookingUi.selected?.checkin):(receipt.date || bookingUi.selected?.date);
      if(/^\d{4}-\d{2}-\d{2}$/.test(day || "")) { $("booking-date").value=day; await changeView(1,kind==="slot"?id:null); }
      else await Promise.allSettled([loadBookings(true),loadStays()]);
      status("new-booking-status","Kinnitus tuli taustsüsteemist. Broneering on ülevaates kontrollitav.");
    } else {
      bookingUi.confirmed=null; $("booking-cancel-request").hidden=true; $("booking-cancel-actions").hidden=true;
      $("booking-receipt-title").textContent="Testbroneering on tühistatud"; status("new-booking-status","Taustsüsteem kinnitas tühistamise.");
      await Promise.allSettled([loadBookings(true),loadStays()]);
    }
  } catch(error) {
    if(error.name!=="AbortError" && generation===state.generation && state.connected) {
      if(!error.status || error.status>=500) bookingUi.uncertain=true;
      status("new-booking-status",error.message+(bookingUi.uncertain?" Tulemust ei korrata automaatselt. Kontrolli broneeringute ülevaadet.":""),"error");
    }
  } finally { if(generation===state.generation) { bookingUi.busy=false; controls(); } }
}
$("booking-search-form").addEventListener("submit",event=>{event.preventDefault();searchBooking();});
$("booking-kind-slot").addEventListener("click",()=>chooseBookingKind("slot"));
$("booking-kind-stay").addEventListener("click",()=>chooseBookingKind("stay"));
$("new-service").addEventListener("change",()=>{clearBookingSelection();updateProviders();});
for(const id of ["new-provider","new-slot-date","new-checkin","new-checkout","new-adults","new-children","new-room-type"]) $(id).addEventListener("change",clearBookingSelection);
$("booking-confirm").addEventListener("click",()=>mutateBooking("confirm"));
$("booking-decline").addEventListener("click",()=>{clearBookingSelection();status("new-booking-status","Loobusid pakkumisest. Broneeringut ei loodud.");});
$("booking-cancel-request").addEventListener("click",()=>{$("booking-cancel-actions").hidden=false;});
$("booking-cancel").addEventListener("click",()=>mutateBooking("cancel"));
$("booking-cancel-decline").addEventListener("click",()=>{$("booking-cancel-actions").hidden=true;});
for(const button of document.querySelectorAll?.(".example-button") || []) button.addEventListener("click",()=>sendTurn({text:button.dataset.message}));
$("new-slot-date").value=dayAfter(tallinnDay()); $("new-checkin").value=dayAfter(tallinnDay()); $("new-checkout").value=dayAfter(tallinnDay(),3);
for(const id of ["new-slot-date","new-checkin","new-checkout"]) $(id).min=tallinnDay();
if(query.get("book")==="stay") chooseBookingKind("stay");
if(["spa","stay"].includes(query.get("book"))) location.hash="#new-booking-section";
