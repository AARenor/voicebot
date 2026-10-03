"use strict";
const historyState = {items:[], summary:null, fetchedAt:null, busy:false, error:false, page:1, hasMore:false, view:0, selected:null, detail:null, detailVersion:0, detailBusy:false};
const historyOutcomes = {in_progress:"Aktiivne", completed:"Lõpetatud", ok:"Vastus antud", tools_ok:"Toimingud kontrollitud", fallback:"Varuvastus", tools_failed:"Toiming vajab kontrolli", tts_failed:"Helivastus puudus", provider_error:"Teenuse viga", booking_unavailable:"Broneerimine ebaõnnestus", unknown_outcome:"Tulemus ebaselge", write_outcome_unknown:"Tulemus ebaselge", hold_created:"Aeg ette valmistatud", booking_confirmed:"Broneering kinnitatud", booking_cancelled:"Broneering tühistatud", interrupted:"Ühendus katkes", expired:"Vestlus aegus"};
const historyEvents = {started:"Vestlus algas", typed:"Tekstsõnum saadeti", recognized:"Kõne tuvastati", no_speech:"Arusaadavat kõnet ei tuvastatud", stt_unavailable:"Kõnetuvastus ei olnud saadaval", speech_started:"Rääkimine tuvastati", greeting:"Tervitus saadeti", interrupted:"Abilise kõne katkestati", response:"Abiline vastas", tts_unavailable:"Helivastus ebaõnnestus", stt_error:"Kõnetuvastuse teenuse viga", tts_error:"Kõnesünteesi teenuse viga", llm_error:"Vastuse teenuse viga", provider_error:"Kõneteenuse viga", booking_confirmed:"Broneering kinnitati", booking_cancelled:"Broneering tühistati", ended:"Vestlus lõppes"};

function historyNode(tag, text="", className="") {
  const node=document.createElement(tag); node.textContent=text; node.className=className; return node;
}
function historyTime(raw, timeOnly=false) {
  const date=new Date(raw);
  if (!Number.isFinite(date.getTime())) return "Aeg puudub";
  return new Intl.DateTimeFormat("et-EE", {timeZone:"Europe/Tallinn", ...(timeOnly ? {} : {day:"2-digit",month:"short"}), hour:"2-digit",minute:"2-digit", ...(timeOnly ? {second:"2-digit"} : {})}).format(date);
}
function historyDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const total=Math.floor(seconds);
  return total < 60 ? `${total} s` : `${Math.floor(total/60)} min ${total%60} s`;
}
function historyLabel(item) { return item.channel === "telephone" ? "Telefonikõne" : "Veebivestlus"; }
function historyBadge(item) {
  return historyNode("span", item.status === "active" ? "Aktiivne" : historyOutcomes[item.outcome] || "Lõpetatud", "call-state" + (item.needs_attention ? " attention" : ""));
}
function historyPlaceholder() {
  const box=historyNode("div", "", "history-detail-placeholder");
  box.append(historyNode("h3", "Vaata, kuidas kõne kulges"),historyNode("p", "Vali vestlus, et näha kõnetuvastust, toiminguid ja broneeringuid."));
  $("history-detail").replaceChildren(box);
}
function historyControls() {
  $("calls-section").setAttribute("aria-busy", String(historyState.busy));
  $("history-detail").setAttribute("aria-busy", String(historyState.detailBusy));
  $("history-refresh").disabled=!state.connected || historyState.busy;
  $("history-channel").disabled=!state.connected;
  $("history-result").disabled=!state.connected;
  $("history-prev").disabled=!state.connected || historyState.busy || historyState.page <= 1;
  $("history-next").disabled=!state.connected || historyState.busy || !historyState.hasMore || historyState.page >= 1000;
}
function resetHistory() {
  Object.assign(historyState, {items:[], summary:null, fetchedAt:null, busy:false, error:false, page:1, hasMore:false, selected:null, detail:null, detailBusy:false});
  historyState.view++; historyState.detailVersion++;
  $("history-list").replaceChildren(); $("history-empty").hidden=true;
  $("history-channel").value="all"; $("history-result").value="all";
  for (const id of ["history-total","history-active","history-booked","history-attention"]) $(id).textContent="—";
  $("history-page").textContent="Leht 1";
  status("history-status", "Ühenda kõneajaloo vaatamiseks."); historyPlaceholder(); historyControls();
}
function renderHistory() {
  const list=$("history-list"); list.replaceChildren();
  for (const item of historyState.items) {
    const row=historyNode("li"), button=historyNode("button", "", "history-row");
    button.type="button"; button.dataset.callId=item.id;
    button.setAttribute("aria-pressed", String(item.id === historyState.selected));
    button.setAttribute("aria-controls", "history-detail");
    const head=historyNode("div", "", "history-row-head"); head.append(historyNode("strong",historyLabel(item)),historyBadge(item));
    const meta=historyNode("div", "", "history-row-meta");
    meta.append(historyNode("span",historyTime(item.started_at)),historyNode("span",historyDuration(item.duration_s)));
    const note=historyNode("div", "", "history-row-meta");
    note.append(historyNode("span",`${item.turns} vooru`),historyNode("span",item.bookings?.length ? `${item.bookings.length} broneering` : "Broneeringuta"));
    button.append(head,meta,note); button.addEventListener("click",()=>selectHistory(item.id)); row.append(button); list.append(row);
  }
  $("history-empty").hidden=!historyState.fetchedAt || historyState.items.length > 0;
  for (const [id,key] of [["history-total","total"],["history-active","active"],["history-booked","with_booking"],["history-attention","needs_attention"]]) {
    $(id).textContent=historyState.summary ? String(historyState.summary[key]) : "—";
  }
  $("history-page").textContent=`Leht ${historyState.page}`;
  historyControls();
}
async function loadHistory() {
  if (!state.connected || historyState.busy) return;
  const generation=state.generation, view=historyState.view;
  const params=new URLSearchParams({page:String(historyState.page),length:"20",channel:$("history-channel").value || "all",result:$("history-result").value || "all"});
  historyState.busy=true; historyControls();
  if (!historyState.fetchedAt) status("history-status", "Laadin vestluste ajalugu…");
  try {
    const data=await api("/api/call-history?" + params);
    if (generation!==state.generation || view!==historyState.view || !state.connected) return;
    if (!Array.isArray(data.items) || !data.summary) throw new Error("Kõneajaloo vastus ei olnud loetav. Proovi uuesti.");
    Object.assign(historyState,{items:data.items,summary:data.summary,fetchedAt:data.fetched_at,error:false,hasMore:data.has_more === true});
    if (historyState.selected && !data.items.some(item=>item.id===historyState.selected)) { historyState.selected=null; historyState.detail=null; historyState.detailVersion++; historyState.detailBusy=false; historyPlaceholder(); }
    renderHistory();
    status("history-status",`${data.summary.total} vestlust valitud filtritega. Uuendatud ${historyTime(data.fetched_at)}.`);
    if (historyState.selected && !historyState.detailBusy) await selectHistory(historyState.selected,true);
  } catch(error) {
    if (error.name!=="AbortError" && generation===state.generation && view===historyState.view && state.connected) {
      historyState.error=true;
      status("history-status", (historyState.fetchedAt ? "Kuvatud ajalugu võib olla aegunud. " : "Kõneajalugu ei saanud laadida. ") + error.message,historyState.fetchedAt ? "stale" : "error");
    }
  } finally { if (generation===state.generation && view===historyState.view) { historyState.busy=false; historyControls(); } }
}
async function changeHistory(page=1) {
  historyState.view++; historyState.detailVersion++;
  Object.assign(historyState,{page,busy:false,items:[],summary:null,fetchedAt:null,hasMore:false,selected:null,detail:null,detailBusy:false});
  historyPlaceholder(); renderHistory(); await loadHistory();
}
function historyInsight(item) {
  if (item.outcome === "unknown_outcome" || item.outcome === "write_outcome_unknown") return "Broneerimise tulemus jäi ebaselgeks. Kontrolli taustsüsteemi enne kinnituse või tühistuse kordamist.";
  if (item.stt_errors) return "Kõnetuvastuse teenus ebaõnnestus. See erineb vaiksest või tuvastamata kõnest; kontrolli kõnepakkuja ühendust.";
  if (item.tts_errors) return "Abilise helivastus ebaõnnestus. Kinnitatud broneeringu tulemust kontrolli allolevalt viitelt.";
  if (item.empty_turns >= 3) return "Mitmest heliproovist ei tuvastatud kõnet. Kontrolli mikrofoni helitaset ja proovi lühikest eestikeelset lauset.";
  if (item.channel === "telephone" && !item.recognized_turns && item.vad_events) return "Rääkimine tuvastati, kuid lõplikku kõnetuvastuse teksti ei saabunud. Kontrolli sisendheli ja kõnetuvastuse teekonda.";
  if (item.channel === "telephone" && !item.recognized_turns) return "Selle kõne jooksul ei registreeritud tuvastatud kõnet. Kontrolli, kas helisisend jõudis abiliseni.";
  if (item.bookings?.length) return "Viited pärinevad taustsüsteemi toimingutest. Lauabroneeringu praegust olekut kontrolli päeva ülevaatest. Varasemad hotelli- ja spaakirjed on arhiveeritud.";
  return "Vestluse toimingud on allpool. Veebivestlus ja telefonikõne kasutavad eraldi heliteekondi.";
}
function renderHistoryDetail(data) {
  const item=data.session, panel=$("history-detail"); panel.replaceChildren();
  const head=historyNode("div", "", "history-detail-heading"), title=historyNode("div");
  title.append(historyNode("h3", historyLabel(item)),historyNode("p",`${historyTime(item.started_at)} · Europe/Tallinn`));
  head.append(title,historyBadge(item)); panel.append(head);
  const stats=historyNode("dl", "", "history-stats");
  for (const [label,value] of [["Kestus",historyDuration(item.duration_s)],["Tuvastatud voorud",item.recognized_turns + item.typed_turns],["Tuvastuse vead",item.stt_errors]]) {
    const pair=historyNode("div"); pair.append(historyNode("dt",label),historyNode("dd",String(value))); stats.append(pair);
  }
  panel.append(stats,historyNode("p",historyInsight(item),"history-insight" + (item.needs_attention ? " attention" : "")));
  if (item.bookings?.length) {
    const bookings=historyNode("div", "", "history-bookings");
    for (const booking of item.bookings) {
      const box=historyNode("div", "", "history-booking"), copy=historyNode("div");
      const table=booking.kind === "table", stay=booking.kind === "stay";
      const label=table ? `Lauabroneering #${booking.id}` : stay ? `Arhiveeritud hotellipeatumine #${booking.id}` : `Arhiveeritud spaa broneering #${booking.id}`;
      const time=typeof booking.start_local==="string" ? booking.start_local.slice(11,16) : booking.start_time || "";
      copy.append(historyNode("strong",label),historyNode("p",`${stay ? `${booking.date} – ${booking.checkout || ""}` : `${booking.date} ${time}`} · ${booking.action === "cancelled" ? "Tühistatud" : "Kinnitatud"}`));
      box.append(copy);
      // Archive metadata keeps its original kind; never point at retired controls.
      if(table && /^\d{4}-\d{2}-\d{2}$/.test(booking.date) && /^table_[a-f0-9]{32}$/.test(booking.id)) {
        const button=historyNode("button","Ava päeva lauabroneeringud","button compact"); button.type="button";
        button.addEventListener("click",async()=>{
          if (!state.connected) return;
          $("booking-date").value=booking.date;
          await changeView(1,booking.action === "confirmed" ? booking.id : null);
          if (!state.connected) return;
          location.hash="booking-section"; $("bookings-title").setAttribute("tabindex","-1"); $("bookings-title").focus?.();
        });
        box.append(button);
      }
      bookings.append(box);
    }
    panel.append(bookings);
  }
  panel.append(historyNode("h4","Vestluse sündmused"));
  const timeline=historyNode("ol", "", "history-timeline");
  for (const event of data.events || []) {
    const entry=historyNode("li"), time=historyNode("time",historyTime(event.at,true)); time.setAttribute("datetime",event.at);
    entry.append(historyNode("strong",(historyEvents[event.kind] || "Toiming salvestati") + (event.kind === "response" ? `: ${historyOutcomes[event.outcome] || "tulemus salvestatud"}` : "")),time); timeline.append(entry);
  }
  panel.append(timeline);
}
async function selectHistory(id, background=false) {
  if (!state.connected || !/^[a-f0-9]{32}$/.test(id)) return;
  const generation=state.generation, version=++historyState.detailVersion;
  historyState.selected=id; historyState.detailBusy=true; renderHistory();
  const previous=background && historyState.detail?.session.id === id ? historyState.detail : null;
  if (!previous) $("history-detail").replaceChildren(historyNode("p","Laadin vestluse üksikasju…","status"));
  try {
    const data=await api("/api/call-history/" + id);
    if (generation!==state.generation || version!==historyState.detailVersion || !state.connected) return;
    if (data.session?.id !== id || !Array.isArray(data.events)) throw new Error("Vestluse üksikasjad ei olnud loetavad.");
    historyState.detail=data; renderHistoryDetail(data);
  } catch(error) {
    if (error.name!=="AbortError" && generation===state.generation && version===historyState.detailVersion && state.connected) {
      const text=historyNode("p",error.status === 404 ? "Seda vestlust enam ajaloos pole. Uuenda ajalugu." : "Vestluse üksikasju ei saanud laadida. " + error.message,"status error");
      const retry=historyNode("button","Proovi uuesti","button compact"); retry.type="button"; retry.addEventListener("click",()=>selectHistory(id));
      if (previous) { renderHistoryDetail(previous); text.textContent="Kuvatud üksikasjad võivad olla aegunud. " + text.textContent; $("history-detail").append(text,retry); }
      else $("history-detail").replaceChildren(text,retry);
    }
  } finally { if(generation===state.generation && version===historyState.detailVersion) { historyState.detailBusy=false; historyControls(); } }
}
function initializeHistory() {
  $("history-refresh").addEventListener("click",loadHistory);
  for (const id of ["history-channel","history-result"]) $(id).addEventListener("change",()=>changeHistory());
  $("history-prev").addEventListener("click",()=>{if(historyState.page>1)changeHistory(historyState.page-1);});
  $("history-next").addEventListener("click",()=>{if(historyState.hasMore)changeHistory(historyState.page+1);});
  historyControls();
}
