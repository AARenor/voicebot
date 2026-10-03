"use strict";
const $ = id => document.getElementById(id);
const state = {credential:"", connected:false, generation:0, controllers:new Set(), bookings:[], fetchedAt:null, hasMore:false, page:1, readBusy:false, bookingError:false, retryAt:0, failures:0, view:0, highlightId:null, sessionId:null, callId:null, turnBusy:false, demoEnding:false, demoEpoch:0, audioUrl:null, audioEpoch:0, playback:null, turnController:null, recap:null, recapDeliveryId:null, mic:null, micStarting:false, micEpoch:0, demoLanguage:"auto", demoVoice:"azure", voiceCatalog:null, endpointingMs:650, replyLanguage:"et", demoModels:null};
const bookingUi = {kind:"table", sessionId:null, busy:false, uncertain:false, holdId:null, recapDeliveryId:null, acknowledged:false, selected:null, confirmed:null, tables:[], rules:null, epoch:0};
const DEMO_COPY = {
  et: {
    title:"Proovi kõneabilist", subtitle:"Kirjuta sõnum või räägi mikrofoniga",
    languageLabel:"Vestluse keel / Conversation language", languageHelp:"Vali keel enne vestlust. Keele muutmiseks lõpeta vestlus ja alusta uut.", voiceLabel:"Abilise hääl / Assistant voice",
    introTitle:"Üks vestlus. Laud ootab.", intro:"Küsi restorani kohta, vali aeg ja inimeste arv ning proovi lauabroneeringut fiktiivse külalisena.",
    start:"Alusta demovestlust", end:"Lõpeta vestlus", history:"Vaata vestluse ajalugu", messageLabel:"Sõnum demoabilisele", send:"Saada sõnum",
    placeholder:"Näiteks: homme kell 18 laud kahele", micLevel:"Mikrofoni helitase", speakNaturally:"Räägi loomulikult.",
    micHelp:"Ühenda esmalt operaatori tunnusega. Häälvestluse nupp alustab vestluse ja küsib mikrofoni luba. Kõnepaus saadab heli automaatselt; teine vajutus saadab kohe. Üks salvestis kestab kuni 15 sekundit.",
    recapRead:"Olen kokkuvõtte läbi lugenud", guidanceTitle:"Kuidas demovestlus töötab?",
    recapHelp:"Kuula broneeringu kokkuvõte algusest lõpuni või loe see vestlusest läbi ja kinnita lugemine. See ei loo broneeringut; kinnitamiseks saada seejärel eraldi sõnum.",
    guidance:"Abiline kasutab selle vestluse fiktiivset külalist. Kuula kokkuvõte algusest lõpuni või kinnita eraldi selle lugemine. Kinnitamiseks ütle pärast kokkuvõtet: „Jah, kinnitan.” Tühistamiseks: „Jah, tühista.” Ära sisesta päris kontaktandmeid. Salvestis ei jää brauserisse. See on fiktiivne HTTP kõneproov, mitte telefonikõne ega päris restorani teenus.",
    examplesLabel:"Vestluse alustamise näited", transcriptLabel:"Selle lehe demovestlus", audioLabel:"Demoabilise vastus",
    examples:{hours:["Lahtiolekuajad","Millal restoran avatud on?"], table:["Laud kahele","Soovin homme kell 18 lauda kahele."], rules:["Broneerimise reeglid","Kui kaua saab lauda kasutada ja kas lapsed lähevad inimeste arvu sisse?"]},
    signIn:"Vestluse alustamiseks sisesta operaatori tunnus ja vajuta „Ühenda”.", ready:"Alusta demovestlust või vajuta „Alusta häälvestlust”. Vestlus aegub 10 minutiga.",
    started:"Fiktiivne vestlus alustatud. Kuula tervitust, seejärel vajuta mikrofoni ja räägi.", greetingFailed:"Tervituse heli pole saadaval. Tekst on alles; jätkamiseks vajuta mikrofoni või kirjuta.",
    responding:"Demoabiline vastab… Ära saada sama kinnitust uuesti.", you:"Sina", assistant:"Demoabiline", heardFailed:"Kõnetuvastus ei olnud saadaval", heardNothing:"Kõnet ei tuvastatud",
    micStart:"Alusta häälvestlust", micReady:"Luba mikrofon ja räägi", micStop:"Lõpeta ja saada heli", micPermission:"Ootan mikrofoni luba…",
    micListening:"Kuulan… Räägi kuni 15 sekundit. Vastus tuleb kõnepausi järel; kohe saatmiseks vajuta uuesti.", micDenied:"Mikrofon ei avanenud. Luba brauseris mikrofon või saada tekstsõnum.",
    micSilent:"Mikrofonist ei saabunud helisignaali. Kontrolli valitud mikrofoni ja proovi uuesti.", micEmpty:"Mikrofonist ei saabunud heli. Proovi uuesti.", micEncoding:"Heliproovi ei saanud ette valmistada.",
    micQuiet:"Heli on vaikne. Kontrolli, kas valitud on õige mikrofon.", micSignal:"Heli jõuab mikrofonist kohale. Lõpetamiseks vajuta uuesti.",
    replyPlayed:"Vastus esitatud. Jätkamiseks vajuta mikrofoni või kirjuta sõnum.", audioError:"Vastuse heli ei saa esitada. Loe vastust tekstina; toimingut ei korrata automaatselt.", audioInvalid:"Vastuse heli on vigane. Loe vastust tekstina; toimingut ei korrata automaatselt.", autoplay:"Brauser ei lubanud heli automaatselt esitada. Vajuta helimängijas „Esita” või loe vastust tekstina.",
    ended:"Vestlus lõpetatud. Broneeringuid see automaatselt ei tühista.", expired:"Vestlus ei ole enam aktiivne. Alusta uut vestlust; ebaselge broneerimise või tühistamise tulemust kontrolli esmalt taustsüsteemist. Broneeringuid see automaatselt ei tühista.",
    noRetry:"Toimingut ei korrata automaatselt. Ebaselge tulemuse korral kontrolli broneeringute tabelit.", textFallback:"Heli pole saadaval; loe vastust tekstina.",
    sttFailed:"Kõnetuvastuse teenus ebaõnnestus. Proovi hetke pärast uuesti või kirjuta sõnum. Kõneajalugu sisaldab vea olekut.", noSpeech:"Kõnet ei tuvastatud. Kontrolli mikrofoni helitaset ja räägi pärast mikrofoni avanemist.",
    outcome:{ok:"Vastus valmis.", tools_ok:"Taustsüsteemi tööriistad vastasid.", tools_failed:"Mõni toiming ebaõnnestus — edu ei ole kinnitatud.", secondaryFailed:"Muu päring ebaõnnestus. Vaata vastust ja kontrolli taustsüsteemi.", unknown_outcome:"Kirjutuse tulemus on ebaselge. Ära korda broneerimist; kontrolli taustsüsteemi.", fallback:"Kasutati varuvastust.", tts_failed:"Kõnesüntees ebaõnnestus; tekst on alles."},
  },
  en: {
    title:"Try the voice assistant", subtitle:"Type a message or speak into your microphone",
    languageLabel:"Conversation language / Vestluse keel", languageHelp:"Choose a language before starting. To change it, end this conversation and start a new one.", voiceLabel:"Assistant voice / Abilise hääl",
    introTitle:"One conversation. A table awaits.", intro:"Ask about the restaurant, choose a time and party size, and try a table booking with a fictional guest.",
    start:"Start demo conversation", end:"End conversation", history:"View conversation history", messageLabel:"Message the demo assistant", send:"Send message",
    placeholder:"For example: a table for two tomorrow at 6 pm", micLevel:"Microphone level", speakNaturally:"Speak naturally.",
    micHelp:"Connect with your operator token first. The voice button starts a conversation and asks for microphone permission. A pause sends your audio automatically; press again to send immediately. Each recording lasts up to 15 seconds.",
    recapRead:"I have read the recap", guidanceTitle:"How does the demo work?",
    recapHelp:"Listen to the booking recap from beginning to end, or read it in the conversation and acknowledge reading. This does not create a booking; send a separate message afterwards to confirm.",
    guidance:"The assistant uses a fictional guest for this conversation. Listen to the whole recap or acknowledge reading it separately. Then say: “Yes, I confirm.” To cancel, say: “Please cancel this test booking.” Do not enter real contact details. Recordings are not kept in your browser. This is a fictional web voice demo, not a telephone call or a real restaurant service.",
    examplesLabel:"Conversation examples", transcriptLabel:"This page's demo conversation", audioLabel:"Demo assistant's reply",
    examples:{hours:["Opening hours","What are the restaurant opening hours?"], table:["Table for two","I would like a table for two tomorrow at 6 pm."], rules:["Booking rules","How long is a sitting, and do children count towards the party size?"]},
    signIn:"To start, enter your operator token and press “Ühenda” (Connect).", ready:"Start a demo conversation or press “Start voice conversation”. The session lasts 10 minutes.",
    started:"Fictional conversation started. Listen to the greeting, then press the microphone button and speak.", greetingFailed:"Greeting audio is unavailable. The text is still here; continue with the microphone or type a message.",
    responding:"The demo assistant is replying… Do not send the same confirmation again.", you:"You", assistant:"Demo assistant", heardFailed:"Speech recognition was unavailable", heardNothing:"No speech detected",
    micStart:"Start voice conversation", micReady:"Enable microphone and speak", micStop:"Stop and send audio", micPermission:"Waiting for microphone permission…",
    micListening:"Listening… Speak for up to 15 seconds. A pause sends your audio; press again to send immediately.", micDenied:"The microphone could not be opened. Allow microphone access in your browser or type a message.",
    micSilent:"No microphone signal was received. Check the selected microphone and try again.", micEmpty:"No microphone audio was received. Please try again.", micEncoding:"The audio sample could not be prepared.",
    micQuiet:"Audio is quiet. Check that the correct microphone is selected.", micSignal:"Microphone audio is being received. Press again to finish.",
    replyPlayed:"Reply played. Press the microphone button or type a message to continue.", audioError:"Reply audio could not be played. Read the reply as text; the action will not be retried automatically.", audioInvalid:"Reply audio is invalid. Read the reply as text; the action will not be retried automatically.", autoplay:"Your browser blocked automatic playback. Press Play in the audio player or read the reply as text.",
    ended:"Conversation ended. This does not cancel any bookings.", expired:"This conversation is no longer active. Start a new one; check any uncertain booking or cancellation in the booking system first. Bookings are not cancelled automatically.",
    noRetry:"The action will not be retried automatically. Check the booking table if the outcome is uncertain.", textFallback:"Audio is unavailable; read the reply as text.",
    sttFailed:"Speech recognition failed. Try again shortly or type a message. The call history records the error status.", noSpeech:"No speech was detected. Check the microphone level and speak after the microphone opens.",
    outcome:{ok:"Reply ready.", tools_ok:"The booking system responded.", tools_failed:"An action failed; success is not confirmed.", secondaryFailed:"Another request failed. Read the reply and check the booking system.", unknown_outcome:"The write outcome is uncertain. Do not repeat the booking; check the booking system.", fallback:"A fallback reply was used.", tts_failed:"Speech synthesis failed; the text is still available."},
  },
};
function demoCopy() { return DEMO_COPY[state.demoLanguage === "en" ? "en" : "et"]; }
function localizeDemo() {
  const copy=demoCopy();
  $("demo-language").value=state.demoLanguage;
  $("demo-section").setAttribute("lang", state.demoLanguage === "en" ? "en" : "et");
  for (const node of document.querySelectorAll?.("[data-demo-copy]") || []) node.textContent=copy[node.dataset.demoCopy];
  for (const button of document.querySelectorAll?.("[data-demo-example]") || []) {
    const example=copy.examples[button.dataset.demoExample]; button.textContent=example[0]; button.dataset.message=example[1];
  }
  $("demo-text").placeholder=copy.placeholder;
  $("demo-examples").setAttribute("aria-label", copy.examplesLabel);
  $("demo-messages").setAttribute("aria-label", copy.transcriptLabel);
  $("demo-audio").setAttribute("aria-label", copy.audioLabel);
  renderDemoModels();
  renderVoices();
}
const VOICE_LABELS={azure:"Azure",elevenlabs:"ElevenLabs",google:"Google Chirp 3 HD",cartesia:"Cartesia"};
const VOICE_REASONS=new Set(["missing_credentials","credentials_missing","not_configured","invalid_configuration","missing_dependency","dependency_missing","dependency_unavailable","missing_voice","missing_voice_id","unsupported_language","provider_unavailable","provider_failed","provider_failure","synthesis_failed","catalog_unavailable","unavailable","disabled","transport_error","request_rejected","rate_limited","invalid_response","completion_incomplete"]);
function voiceReason(code) { return VOICE_REASONS.has(code) ? code : "unavailable"; }
function renderVoices() {
  const english=state.demoLanguage==="en", catalog=state.voiceCatalog;
  const profiles=catalog || Object.entries(VOICE_LABELS).map(([id,label])=>({id,label,languages:id==="cartesia"?["en","ru"]:["et","en","ru"],configured:false,available:false,disabled_reason:"catalog_unavailable",legacy:id==="azure"}));
  const select=$("demo-voice"), reasons=[];
  select.replaceChildren();
  for(const profile of profiles) {
    const unsupported=state.demoLanguage!=="auto" && !profile.languages.includes(state.demoLanguage);
    const unavailable=!profile.legacy && (profile.configured!==true || profile.available!==true);
    const reason=unsupported ? "unsupported_language" : unavailable ? voiceReason(profile.disabled_reason) : profile.legacy ? "catalog_unavailable" : null;
    const option=document.createElement("option"); option.value=profile.id; option.disabled=unsupported || unavailable;
    option.textContent=profile.label + (reason ? ` (${reason})` : "") + (profile.id==="cartesia" && state.demoLanguage==="auto" ? english ? " — Azure for Estonian" : " — eesti keeles Azure" : "");
    select.append(option);
    if(reason) reasons.push(`${profile.label}: ${reason}.`);
  }
  if(!state.sessionId && !Array.from(select.children).some(option=>option.value===state.demoVoice && !option.disabled)) state.demoVoice="azure";
  select.value=state.demoVoice;
  $("demo-voice-help").textContent=(english ? "Choose before starting; the voice stays fixed for this conversation. Configuration is not a quality or live-availability test. " : "Vali enne vestlust; hääl on selle vestluse ajal lukus. Seadistus ei tõenda kvaliteeti ega teenuse toimimist. ") + reasons.join(" ") + (reasons.length ? english ? " Set the provider credentials and licensed voice in the server environment; install required server dependencies and restart. Azure remains the legacy default when the catalog is unavailable." : " Seadista pakkuja tunnused ja lubatud hääl serveri keskkonnas, paigalda vajalikud serveri sõltuvused ning taaskäivita. Puuduva kataloogi korral jääb vaikimisi Azure." : "");
}
async function loadVoices() {
  if(!state.connected) return;
  const generation=state.generation;
  try {
    const data=await api("/api/demo/voices");
    if(generation!==state.generation || !state.connected) return;
    const ids=new Set();
    if(!Array.isArray(data.voices) || !data.voices.length || data.voices.length>4 || data.voices.some(profile=>!profile || !Object.hasOwn(VOICE_LABELS,profile.id) || ids.has(profile.id) || !ids.add(profile.id) || typeof profile.label!=="string" || profile.label.length>80 || !Array.isArray(profile.languages) || !profile.languages.length || profile.languages.some(lang=>!["et","en","ru"].includes(lang)) || typeof profile.configured!=="boolean" || typeof profile.available!=="boolean" || typeof profile.streaming!=="boolean") || !ids.has("azure")) throw new Error("catalog_unavailable");
    state.voiceCatalog=data.voices;
    state.endpointingMs=Number.isInteger(data.endpointing_ms) && data.endpointing_ms>=300 && data.endpointing_ms<=2000 ? data.endpointing_ms : 650;
  } catch(_) { if(generation!==state.generation || !state.connected) return; state.voiceCatalog=null; state.endpointingMs=650; }
  renderVoices(); controls();
}
function changeDemoVoice() {
  if(!state.connected || state.sessionId || state.turnBusy || state.mic || state.micStarting) { $("demo-voice").value=state.demoVoice; return; }
  const option=Array.from($("demo-voice").children).find(item=>item.value===$("demo-voice").value && !item.disabled);
  if(option) { stopAudio(); state.demoVoice=option.value; $("demo-voice-result").textContent=""; }
  renderVoices(); controls();
}
function renderVoiceResult(data) {
  const voice=data.voice, english=state.demoLanguage==="en";
  if(data.tts_failed || data.outcome==="tts_failed") { $("demo-voice-result").textContent=english ? "Reply audio failed; effective voice unverified." : "Vastuse heli ebaõnnestus; kasutatud hääl kontrollimata."; return; }
  if(!voice || !Object.hasOwn(VOICE_LABELS,voice.effective) || !Object.hasOwn(VOICE_LABELS,voice.requested) || typeof voice.fallback!=="boolean") { $("demo-voice-result").textContent=english ? "Effective voice unverified: server metadata unavailable." : "Kasutatud hääl kontrollimata: serveri teave puudub."; return; }
  $("demo-voice-result").textContent=(english ? "Reply voice: " : "Vastuse hääl: ") + VOICE_LABELS[voice.effective] + (voice.fallback ? ` (${english ? "fallback from " : "varuhääl, valitud "}${VOICE_LABELS[voice.requested]}: ${voiceReason(voice.reason)})` : "") + (voice.streaming===false ? english ? "; provider audio is buffered." : "; pakkuja heli on puhverdatud." : "");
}
function renderDemoModels() {
  const models=state.demoModels?.models;
  if (!models) { $("demo-models").textContent=state.demoLanguage === "en" ? "Checking the server's speech configuration." : "Mudelite seadistust kontrollitakse serverist."; return; }
  const voice=state.demoLanguage === "en" ? state.demoModels.englishVoice : models.tts?.voice;
  $("demo-models").textContent=state.demoLanguage === "en" ? `Configured: transcription ${models.stt?.model || "unavailable"}; replies ${models.llm?.model || "unavailable"}; voice ${voice || "unavailable"}. Configuration does not prove a successful telephone call.` : `Seadistatud: transkriptsioon ${models.stt?.model || "puudub"}; vastused ${models.llm?.model || "puudub"}; hääl ${voice || "puudub"}. Seadistus ei tõenda edukat telefonikõnet.`;
}
function changeDemoLanguage() {
  if (state.sessionId || state.turnBusy || state.mic || state.micStarting) { $("demo-language").value=state.demoLanguage; return; }
  const selected=$("demo-language").value;
  state.demoLanguage=["auto","et","en"].includes(selected) ? selected : "auto";
  $("demo-language").value=state.demoLanguage;
  localizeDemo();
  $("demo-warning").hidden=true; $("demo-warning").textContent=""; $("demo-timings").hidden=true;
  $("demo-voice-result").textContent="";
  status("demo-status", state.connected ? demoCopy().ready : demoCopy().signIn);
  controls();
}
function recapPlayedMessage(heard) {
  const words={et:"Jah, kinnitan.", en:"Yes, I confirm.", ru:"Да, подтверждаю."}[state.replyLanguage] || "Jah, kinnitan.";
  return state.demoLanguage === "en" ? `Recap ${heard?"heard in full":"read"}. No booking has been created. To confirm, send a separate “${words}” message. Make a new request to change the proposal.` : `Kokkuvõte on ${heard?"kuulatud":"läbi loetud"}. Broneeringut veel ei loodud. Kinnitamiseks saada eraldi „${words}”`;
}
function demoError(error) {
  if (state.demoLanguage !== "en") return error.message;
  const known={recap_delivery_expired_or_unknown:"The booking recap has changed or expired. Request a new recap and listen to it in full or acknowledge reading before giving new consent.", voice_stack_not_configured:"The voice demo is not configured on the server.", demo_sessions_full:"All demo conversations are busy. Please try again shortly.", demo_session_language_invalid:"Choose a supported conversation language.", stt_not_configured:"Speech recognition is not configured. Please type a message."};
  return known[error.code] || ({401:"The operator token is missing or invalid. Connect again.",403:"The operator token is missing or invalid. Connect again.",404:demoCopy().expired,410:demoCopy().expired,409:"The conversation is processing the previous message. Wait for its reply.",413:"The message or recording is too long. Try a shorter sample.",400:"Check the message or language selection."})[error.status] || "The request failed or timed out. Check the booking system before repeating a confirmation or cancellation.";
}
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
  $("auth-description").textContent = state.connected ? "Operaatori seanss on aktiivne." : "Lauabroneeringute, reeglite ja kõneproovi avamiseks.";
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
  $("overview-tables").textContent = state.fetchedAt ? String(state.bookings.filter(item=>item.status==="confirmed").length) : "—";
  $("overview-inventory").textContent = bookingUi.rules ? String(bookingUi.tables.length) : "—";
  $("new-booking-section").setAttribute("aria-busy", String(bookingUi.busy));
  $("mic-feedback").hidden=!state.mic;
}
function clearRecap() {
  clearTimeout(state.recap?.timer);
  state.recap=null; state.recapDeliveryId=null;
  $("demo-recap-actions").hidden=true;
}
function currentRecap(recap) {
  return !!recap && state.recap===recap && state.connected && recap.generation===state.generation && recap.sessionId===state.sessionId && Date.now()<recap.expiresAt && $("demo-messages").contains(recap.message) && recap.message.querySelector("span")?.textContent===recap.reply;
}
function acknowledgeRecap(recap, heard=false) {
  if(!currentRecap(recap) || state.turnBusy || recap.acknowledged) return;
  recap.acknowledged=true; state.recapDeliveryId=recap.id;
  $("demo-recap-actions").hidden=true;
  status("demo-status", recapPlayedMessage(heard));
}
function renderRecap(data, message, receivedAt=Date.now()) {
  if(typeof data.recap_delivery_id!=="string" || !/^[a-f0-9]{32}$/.test(data.recap_delivery_id) || !Number.isFinite(data.recap_expires_in_s) || data.recap_expires_in_s<=0 || typeof data.reply!=="string" || !data.reply.trim() || ["fallback","tools_failed","unknown_outcome"].includes(data.outcome)) return null;
  const expiresAt=receivedAt+data.recap_expires_in_s*1000;
  if(expiresAt<=Date.now()) return null;
  const recap={id:data.recap_delivery_id,sessionId:state.sessionId,generation:state.generation,expiresAt,message,reply:data.reply,acknowledged:false};
  state.recap=recap;
  recap.timer=setTimeout(()=>{if(state.recap===recap)clearRecap();},expiresAt-Date.now());
  $("demo-recap-actions").hidden=false;
  return recap;
}
function fullPlayback(audio) {
  // An ended event also follows seeking; only contiguous played ranges deliver a recap.
  if(!audio.ended || !Number.isFinite(audio.duration) || audio.duration<=0 || !audio.played.length) return false;
  let through=0;
  for(let i=0;i<audio.played.length;i++) {
    if(audio.played.start(i)>through+.001) return false;
    through=Math.max(through,audio.played.end(i));
  }
  return through>=audio.duration-.001;
}
function releaseAudio(playback) {
  if(playback) {
    playback.queue.length=playback.chunks.length=0;
    if(playback.source) {
      playback.source.onsourceopen=playback.source.onsourceclose=null;
      if(playback.buffer) {
        playback.buffer.onupdateend=playback.buffer.onerror=playback.buffer.onabort=null;
        try { playback.buffer.abort(); playback.source.removeSourceBuffer(playback.buffer); } catch(_) {}
      }
      try { if(playback.source.readyState==="open") playback.source.endOfStream(); } catch(_) {}
    }
    playback.source=playback.buffer=null; playback.url=null;
  }
  $("demo-audio").onended = $("demo-audio").onpause = $("demo-audio").onerror = $("demo-audio").onplaying = $("demo-audio").onseeking = $("demo-audio").onwaiting = $("demo-audio").onstalled = null;
  $("demo-audio").pause(); $("demo-audio").removeAttribute("src"); $("demo-audio").load(); $("demo-audio").hidden = true;
  if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
  state.audioUrl = null;
}
function stopAudio(preserveDelivered=false) {
  // Starting capture may retain a completed/read receipt, never a partial recap.
  if(!preserveDelivered || !state.recapDeliveryId || !currentRecap(state.recap)) clearRecap();
  state.audioEpoch++;
  const playback=state.playback; state.playback=null;
  state.turnController?.abort(); state.turnController=null;
  playback?.reader?.cancel().catch(()=>{});
  releaseAudio(playback);
}
const MAX_REPLY_AUDIO=8*1024*1024;
const MAX_REPLY_WIRE=12*1024*1024; // Base64 expansion plus bounded event metadata.
function audioBytes(value, limit=MAX_REPLY_AUDIO) {
  if(typeof value!=="string" || !value.length || value.length%4 || value.length>Math.ceil(limit/3)*4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) throw new Error(demoCopy().audioInvalid);
  const raw=atob(value);
  if(!raw.length || raw.length>limit || btoa(raw)!==value) throw new Error(demoCopy().audioInvalid);
  return Uint8Array.from(raw,c=>c.charCodeAt(0));
}
function currentPlayback(playback) { return !!playback && state.connected && playback===state.playback && playback.generation===state.generation && playback.session===state.sessionId && playback.epoch===state.audioEpoch && (!playback.url || (playback.url===state.audioUrl && playback.url===$("demo-audio").src)); }
function newPlayback(recap=null) {
  const playback={generation:state.generation,session:state.sessionId,epoch:state.audioEpoch,queue:[],chunks:[],reader:null,source:null,buffer:null,complete:false,eof:false,appended:false,started:false,seeked:false,interrupted:false,earlyEnd:false,failed:false,recap,resultStatus:$("demo-status").textContent,resultError:false};
  state.playback=playback; return playback;
}
function failPlayback(playback) {
  if(!currentPlayback(playback)) return;
  playback.failed=true;
  // A media failure retires audio, not a successfully validated canonical text recap.
  // Continue bounded stream parsing so only an exact terminal done can permit reading.
  releaseAudio(playback);
  status("demo-status",playback.resultStatus+" "+demoCopy().audioError,"error"); controls();
}
function bindPlayback(playback, source) {
  const audio=$("demo-audio");
  state.audioUrl=playback.url=URL.createObjectURL(source); audio.src=state.audioUrl; audio.hidden=false;
  audio.onplaying=()=>{if(currentPlayback(playback)) playback.started=true;};
  audio.onseeking=()=>{if(currentPlayback(playback)) playback.seeked=true;};
  audio.onpause=()=>{if(currentPlayback(playback) && playback.started && !audio.ended) playback.interrupted=true;};
  audio.onwaiting=audio.onstalled=()=>{if(currentPlayback(playback) && playback.started && audio.currentTime>0) playback.interrupted=true;};
  audio.onended=()=>{
    if(!currentPlayback(playback) || !playback.url || audio.currentSrc!==playback.url || !audio.ended) return;
    if(!playback.complete || !playback.eof || !playback.appended) { playback.earlyEnd=true; return; }
    if(playback.failed || playback.seeked || playback.interrupted || playback.earlyEnd || !playback.started || (playback.source && playback.source.readyState!=="ended") || !fullPlayback(audio)) return;
    if(playback.recap) acknowledgeRecap(playback.recap,true);
    else status("demo-status",playback.resultStatus+" "+demoCopy().replyPlayed,playback.resultError ? "error" : "");
  };
  audio.onerror=()=>failPlayback(playback);
}
function startPlayback(playback) {
  try { $("demo-audio").play().catch(()=>{ if(currentPlayback(playback)) { playback.started=false; status("demo-status",playback.resultStatus+" "+demoCopy().autoplay,"error"); } }); }
  catch(_) { if(currentPlayback(playback)) status("demo-status",playback.resultStatus+" "+demoCopy().autoplay,"error"); }
}
function playbackResult(data, playback) {
  playback.resultStatus=$("demo-status").textContent; playback.resultError=["unknown_outcome","tools_failed","tts_failed"].includes(data.outcome);
}
function playReply(data, recap=null) {
  const playback=newPlayback(recap); playback.complete=playback.eof=playback.appended=true;
  playbackResult(data,playback);
  if (!data.audio_b64) return;
  try {
    bindPlayback(playback,new Blob([audioBytes(data.audio_b64)],{type:data.audio_type==="audio/wav" ? "audio/wav" : "audio/mpeg"}));
    startPlayback(playback);
  } catch(_) { failPlayback(playback); }
}
function appendStreamAudio(playback, bytes) {
  if(!currentPlayback(playback)) throw new DOMException("Playback retired","AbortError");
  if(playback.failed) return;
  const Media=window.MediaSource;
  if(!Media || !Media.isTypeSupported("audio/mpeg")) { playback.chunks.push(bytes); return; }
  playback.queue.push(bytes);
  if(!playback.source) {
    playback.source=new Media(); bindPlayback(playback,playback.source);
    playback.source.onsourceopen=()=>{
      if(!currentPlayback(playback)) return;
      try {
        playback.buffer=playback.source.addSourceBuffer("audio/mpeg");
        playback.buffer.onupdateend=()=>pumpStreamAudio(playback);
        playback.buffer.onerror=playback.buffer.onabort=()=>failPlayback(playback);
        pumpStreamAudio(playback);
      } catch(_) { failPlayback(playback); }
    };
    playback.source.onsourceclose=()=>{if(!playback.appended)failPlayback(playback);};
  } else pumpStreamAudio(playback);
}
function pumpStreamAudio(playback) {
  if(!currentPlayback(playback) || !playback.buffer || playback.buffer.updating || playback.failed) return;
  try {
    if(playback.queue.length) {
      playback.buffer.appendBuffer(playback.queue.shift());
      if(!playback.playAttempted) { playback.playAttempted=true; startPlayback(playback); }
    } else if(playback.eof && !playback.appended) {
      playback.source.endOfStream(); playback.appended=true;
    }
  } catch(_) { failPlayback(playback); }
}
async function readTurnStream(response, controller) {
  if(!response.body) throw new Error(demoCopy().audioInvalid);
  const playback=newPlayback(), reader=response.body.getReader(), decoder=new TextDecoder("utf-8",{fatal:true});
  playback.reader=reader;
  let pending="", wireBytes=0, totalAudio=0, seq=0, lines=0, reply=null, done=null, replyNode=null, receivedAt=null;
  const invalid=()=>{throw new Error(demoCopy().audioInvalid);};
  const consume=line=>{
    if(!line.trim()) return;
    if(line.length>256*1024 || ++lines>8192 || done) invalid();
    let event; try { event=JSON.parse(line); } catch(_) { invalid(); }
    if(!event || Array.isArray(event) || typeof event!=="object" || typeof event.type!=="string" || (event.type!=="done" && Object.hasOwn(event,"recap_delivery_id"))) invalid();
    if(event.type==="reply") {
      if(reply || seq || Object.keys(event).some(key=>!["type","reply","language","audio_type"].includes(key)) || typeof event.reply!=="string" || !event.reply.length || event.reply.length>32768 || !["et","en","ru"].includes(event.language) || event.audio_type!=="audio/mpeg") invalid();
      reply=event; state.replyLanguage=event.language; replyNode=addMessage(demoCopy().assistant,event.reply);
    } else if(event.type==="audio") {
      if(!reply || event.seq!==seq || Object.keys(event).some(key=>!["type","seq","audio_b64"].includes(key))) invalid();
      const bytes=audioBytes(event.audio_b64,128*1024); totalAudio+=bytes.length;
      if(totalAudio>MAX_REPLY_AUDIO) invalid(); seq++; appendStreamAudio(playback,bytes);
    } else if(event.type==="done") {
      if(!reply || event.reply!==reply.reply || event.language!==reply.language || event.audio_type!=="audio/mpeg" || event.audio_b64!=="" || !["ok","tools_ok","tools_failed","unknown_outcome","fallback","tts_failed"].includes(event.outcome) || (event.booking_changes!==undefined && !Array.isArray(event.booking_changes)) || (event.tts_failed!==undefined && typeof event.tts_failed!=="boolean") || (event.recap_delivery_id!=null && (!/^[a-f0-9]{32}$/.test(event.recap_delivery_id) || !seq || event.tts_failed || event.outcome==="tts_failed"))) invalid();
      done=event; receivedAt=Date.now();
    } else invalid();
  };
  const abort=()=>reader.cancel().catch(()=>{});
  controller.signal.addEventListener("abort",abort,{once:true});
  try {
    while(true) {
      const part=await reader.read();
      if(controller.signal.aborted || !currentPlayback(playback)) throw new DOMException("Playback retired","AbortError");
      if(part.done) break;
      wireBytes+=part.value.byteLength; if(wireBytes>MAX_REPLY_WIRE) invalid();
      pending+=decoder.decode(part.value,{stream:true});
      let newline;
      while((newline=pending.indexOf("\n"))!==-1) { consume(pending.slice(0,newline)); pending=pending.slice(newline+1); }
      if(pending.length>256*1024) invalid();
    }
    pending+=decoder.decode();
    if(pending.length || !reply || !done) invalid();
    playback.reader=null;
    playback.complete=playback.eof=true;
    if(done.tts_failed || done.outcome==="tts_failed" || !seq) { playback.failed=true; releaseAudio(playback); }
    else pumpStreamAudio(playback);
    return {...done,_stream:{playback,replyNode,receivedAt}};
  } catch(error) { if(currentPlayback(playback)) stopAudio(); throw error; }
  finally { controller.signal.removeEventListener("abort",abort); await reader.cancel().catch(()=>{}); reader.releaseLock(); }
}
function finishStreamPlayback(data, recap) {
  const playback=data._stream.playback;
  if(!currentPlayback(playback)) return;
  playback.recap=recap; playbackResult(data,playback);
  if(playback.failed) { status("demo-status",playback.resultStatus+" "+demoCopy().audioError,"error"); return; }
  if(!playback.source && playback.chunks.length) {
    playback.appended=true;
    bindPlayback(playback,new Blob(playback.chunks,{type:"audio/mpeg"})); playback.chunks.length=0;
    startPlayback(playback);
  }
}
function stopMic() {
  // Local cancellation also retires permission/encoding still awaiting a result.
  state.micEpoch++; state.micStarting=false;
  const mic = state.mic; state.mic = null;
  if (!mic) { controls(); return null; }
  clearTimeout(mic.timer);
  mic.stream.getTracks().forEach(track => track.stop());
  mic.processor.disconnect(); mic.source.disconnect(); mic.gain.disconnect();
  mic.context.close().catch(() => {});
  $("demo-mic").textContent = demoCopy().micReady;
  controls();
  return mic;
}
function controls() {
  $("logout").disabled = !state.connected;
  $("connect").disabled = !!state.credential;
  $("refresh").disabled = !state.connected || state.readBusy;
  const connecting = !!state.credential && !state.connected;
  $("demo-language").disabled = connecting || !!state.sessionId || state.turnBusy || !!state.mic || state.micStarting;
  $("demo-voice").disabled = !state.connected || !!state.sessionId || state.turnBusy || !!state.mic || state.micStarting;
  $("demo-start").disabled = connecting || !!state.sessionId || state.turnBusy;
  $("demo-end").disabled = !state.sessionId || state.demoEnding;
  for (const id of ["demo-text", "demo-send"]) $(id).disabled = !state.sessionId || state.turnBusy || state.micStarting;
  $("demo-mic").disabled = connecting || state.turnBusy || state.micStarting;
  if (!state.mic) $("demo-mic").textContent = state.sessionId ? demoCopy().micReady : demoCopy().micStart;
  $("demo-recap-read").disabled=!currentRecap(state.recap) || state.turnBusy || state.recap.acknowledged;
  $("demo-history").hidden=!state.callId;
  $("demo-history").disabled=!state.connected;
  $("booking-prev").disabled = !state.connected || state.readBusy || state.page <= 1;
  $("booking-next").disabled = !state.connected || state.readBusy || !state.hasMore || state.page >= 100;
  bookingControls();
  for (const button of document.querySelectorAll?.(".example-button") || []) button.disabled = !state.sessionId || state.turnBusy || state.micStarting;
  presentation();
  historyControls();
}
function logout(message="Ühendus lõpetatud. Privaatseid andmeid enam ei kuvata.", kind="") {
  state.generation++;
  state.controllers.forEach(controller => controller.abort()); state.controllers.clear();
  stopMic(); stopAudio();
  Object.assign(state, {credential:"", connected:false, bookings:[], fetchedAt:null, hasMore:false, readBusy:false, bookingError:false, retryAt:0, failures:0, highlightId:null, sessionId:null, callId:null, turnBusy:false, demoEnding:false, micStarting:false});
  state.voiceCatalog=null; state.demoVoice="azure"; state.endpointingMs=650; renderVoices(); $("demo-voice-result").textContent="";
  resetBookingUi();
  $("token").value = ""; $("demo-text").value = "";
  $("demo-warning").hidden=true; $("demo-warning").textContent=""; $("demo-timings").hidden=true; $("demo-timings").textContent="";
  document.querySelector("#bookings tbody").replaceChildren();
  for (const id of ["calls", "catalogue", "demo-messages"]) $(id).replaceChildren();
  $("booking-empty").hidden = true;
  status("auth-status", message, kind);
  status("booking-status", "Andmed on privaatsed. Ühenda esmalt.");
  status("catalogue-status", "Ühenda laudade vaatamiseks.");
  status("calls-status", "Ühenda päeviku vaatamiseks.");
  status("demo-status", demoCopy().signIn);
  resetHistory();
  controls();
}
async function api(path, opts={}) {
  const isPrivate = path !== "/api/status";
  if (isPrivate && !state.credential) throw new DOMException("Signed out", "AbortError");
  const generation = state.generation;
  const streaming=path==="/api/turn" && new Headers(opts.headers || {}).get("Accept")==="application/x-ndjson", epoch=state.audioEpoch, session=state.sessionId;
  const controller = new AbortController();
  if(streaming) state.turnController=controller;
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
      const explanations={recap_delivery_expired_or_unknown:"Broneeringu kokkuvõte muutus või aegus. Küsi uut kokkuvõtet ja kuula see lõpuni või kinnita selle lugemine enne uut nõusolekut.",booking_recap_expired_or_unknown:"Kokkuvõte aegus või muutus. Valmista pakkumine uuesti ette ja loe uus kokkuvõte läbi.",booking_not_owned_or_cancellation_unavailable:"Seda broneeringut ei saa selles seansis tühistada. Kontrolli broneeringut operaatori taustsüsteemist.",explicit_consent_required:"Kinnitamiseks või tühistamiseks on vaja sinu selget nõusolekut.",booking_date_invalid:"Kuupäev ei sobi. Vali lubatud vahemikus tulevane kuupäev.",table_booking_not_configured:"Restorani broneerimise taustsüsteem pole seadistatud.",voice_stack_not_configured:"Kõneproovi mudel või kõnesüntees pole serveris seadistatud.",mutation_outcome_unknown:"Broneerimise tulemus on ebaselge. Ära korda kinnitamist; kontrolli broneeringute ülevaadet.",write_outcome_unknown:"Broneerimise tulemus on ebaselge. Ära korda kinnitamist; kontrolli broneeringute ülevaadet.",cancel_outcome_unknown:"Tühistamise tulemus on ebaselge. Ära korda tühistamist; kontrolli broneeringute ülevaadet."};
      const message=explanations[problem.detail || problem.error] || (response.status === 403 || response.status === 401 ? "Tunnus puudub või on vale. Ühenda uuesti." : response.status === 410 ? "Vestlus aegus. Alusta uut vestlust; ära korda ebaselget broneerimist." : response.status === 409 ? (path.startsWith("/api/booking/")?"Pakkumine muutus, aegus või toiming ei ole selles seansis võimalik. Kontrolli valikut ja otsi saadavust uuesti.":"Vestlus töötleb eelmist sõnumit. Oota vastus ära.") : response.status === 413 ? "Sõnum või helisalvestis on liiga pikk. Tee lühem proov." : response.status === 400 ? "Kontrolli kuupäeva või sõnumi vormingut." : "Teenus ei ole praegu saadaval. Kontrolli seadistust või proovi hiljem uuesti.");
      const error = new Error(message);
      error.status = response.status;
      error.code = problem.detail || problem.error;
      if (isPrivate && (response.status === 403 || response.status === 401)) logout(error.message, "error");
      throw error;
    }
    if(streaming && (epoch!==state.audioEpoch || session!==state.sessionId)) throw new DOMException("Playback retired","AbortError");
    const data = streaming && response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase()==="application/x-ndjson" ? await readTurnStream(response,controller) : await response.json();
    if (isPrivate && generation !== state.generation) throw new DOMException("Signed out", "AbortError");
    if(streaming && !data._stream && (epoch!==state.audioEpoch || session!==state.sessionId)) throw new DOMException("Playback retired","AbortError");
    return data;
  } catch (error) {
    if (timedOut && generation === state.generation) throw new Error(path === "/api/turn" ? "Vastuse ooteaeg sai läbi. Tulemus võib olla ebaselge; ära korda kinnitust ega tühistust enne taustsüsteemi kontrolli." : "Ühenduse ooteaeg sai läbi. Kontrolli ühendust ja proovi hiljem uuesti.");
    throw error;
  } finally { clearTimeout(deadline); state.controllers.delete(controller); if(state.turnController===controller)state.turnController=null; }
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
    status("new-booking-status","Vali kuupäev, Tallinna kellaaeg ja inimeste arv. Saadavus kontrollitakse taustsüsteemist.");
    status("demo-status", demoCopy().ready); controls();
    await Promise.allSettled([loadBookings(true), loadCatalogue(), loadHistory(), loadStatus(), loadVoices()]);
  } catch (error) {
    if (error.name !== "AbortError") logout(error.message, "error");
  }
}
function localBookingRange(start, end) {
  // Aware restaurant instants are always displayed in Tallinn, never device time.
  if (/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(start || "") && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(end || "")) {
    const first=new Date(start), last=new Date(end);
    if (Number.isFinite(first.getTime()) && Number.isFinite(last.getTime())) {
      const time=new Intl.DateTimeFormat("et-EE",{timeZone:"Europe/Tallinn",hour:"2-digit",minute:"2-digit"});
      const date=new Intl.DateTimeFormat("et-EE",{timeZone:"Europe/Tallinn",day:"2-digit",month:"2-digit",year:"numeric"});
      return date.format(first)===date.format(last) ? {time:`${time.format(first)} – ${time.format(last)}`,date:date.format(first)} : {time:`${date.format(first)} ${time.format(first)} – ${date.format(last)} ${time.format(last)}`,date:""};
    }
  }
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
    const range = localBookingRange(item.start_local || item.start, item.end_local || item.end);
    const cells = [["Laud", item.table_name || item.table_id], ["Inimesi", item.party_size], ["Algus ja lõpp", range.time], ["Ajavöönd", item.timezone || "Kinnitamata"], ["Taustsüsteemi olek", item.status], ["Viide", String(item.id)]];
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
  const params = new URLSearchParams({date:$("booking-date").value});
  state.readBusy = true; state.bookingError = false; controls(); status("booking-status", "Laadin taustsüsteemi broneeringuid…");
  try {
    const data = await api("/api/table-bookings?" + params);
    if (generation !== state.generation || !state.connected || view !== state.view) return;
    if (!Array.isArray(data.items)) throw new Error("Lauabroneeringute vastus ei olnud loetav. Tühi päev pole kinnitatud.");
    Object.assign(state, {bookings:data.items.slice((state.page-1)*50,state.page*50), fetchedAt:data.fetched_at || new Date().toISOString(), hasMore:data.items.length>state.page*50, failures:0, retryAt:0});
    renderBookings(); status("booking-status", `Taustsüsteemist kontrollitud. Uuendatud ${historyTime(state.fetchedAt)}.`);
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
    const data = await api("/api/tables");
    if(generation!==state.generation || !state.connected) return;
    if (!Array.isArray(data.tables) || !data.rules) throw new Error("Restorani kataloog ei olnud loetav. Saadavust see ei kinnita.");
    bookingUi.tables=data.tables; bookingUi.rules=data.rules;
    $("new-party-size").max=String(data.rules.max_party_size);
    $("catalogue").replaceChildren();
    for (const table of data.tables) {
      const item=document.createElement("li"); item.textContent=table.name;
      const note=document.createElement("span"); note.className="sub"; note.textContent=`Kuni ${table.capacity} inimest · eraldi laud`; item.append(note); $("catalogue").append(item);
    }
    $("table-rules").textContent=tableRulesText(data.rules);
    status("catalogue-status", data.tables.length ? "Lauad ja reeglid taustsüsteemist. See ei ole saadavuse kinnitus." : "Taustsüsteemis pole laudu.");
    presentation();
  } catch (error) { if (error.name !== "AbortError" && generation===state.generation && state.connected) { status("catalogue-status",(bookingUi.rules?"Kataloog võib olla aegunud. ":"")+error.message,bookingUi.rules?"stale":"error"); } }
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
    state.demoModels={models:data.models || {},englishVoice:telephone.english_voice};
    renderDemoModels();
  } catch (_) { $("mode").textContent="HTTP kõneproov: olek kontrollimata"; $("overview-voice").textContent="Kontrollimata"; for(const id of ["stack-stt","stack-llm","stack-tts","stack-booking"]) { $(id).textContent="Kontrollimata"; $(id).className=""; } }
}
function addMessage(label, text) {
  const item=document.createElement("li"), author=document.createElement("strong"), content=document.createElement("span");
  item.className=["Sina","You"].includes(label) ? "user-message" : "assistant-message";
  item.setAttribute("lang", state.replyLanguage);
  author.textContent=label; content.textContent=text; item.append(author,content); $("demo-messages").append(item);
  $("demo-messages").scrollTop=$("demo-messages").scrollHeight;
  return item;
}
function requireDemoConnection() {
  if (state.connected) return true;
  status("demo-status", demoCopy().signIn);
  $("token").focus();
  return false;
}
async function startDemo() {
  if (state.turnBusy || state.sessionId || !requireDemoConnection()) return;
  state.turnBusy=true; controls();
  const generation=state.generation, demoEpoch=++state.demoEpoch;
  try {
    const data=await api("/api/demo/session", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({language:state.demoLanguage,voice:state.demoVoice})});
    if(generation!==state.generation || demoEpoch!==state.demoEpoch || !state.connected) return;
    state.sessionId=data.session_id;
    state.replyLanguage=["et","en","ru"].includes(data.language) ? data.language : state.demoLanguage === "en" ? "en" : "et";
    state.callId=/^[a-f0-9]{32}$/.test(data.call_id || "") ? data.call_id : null;
    $("demo-messages").replaceChildren();
    addMessage(demoCopy().assistant, data.greeting);
    status("demo-status", data.tts_failed ? demoCopy().greetingFailed : demoCopy().started, data.tts_failed ? "error" : "");
    renderVoiceResult(data);
    stopAudio(); playReply(data); void loadHistory();
  }
  catch(error) { if(error.name!=="AbortError" && state.connected) status("demo-status", demoError(error), "error"); }
  finally { if(generation===state.generation && demoEpoch===state.demoEpoch) { state.turnBusy=false; controls(); } }
}
async function sendTurn(input) {
  if (!state.sessionId || state.turnBusy || state.micStarting || !state.connected) return;
  const generation=state.generation, session=state.sessionId, demoEpoch=++state.demoEpoch;
  const receipt=currentRecap(state.recap) ? state.recapDeliveryId : null;
  state.turnBusy=true; controls(); stopAudio(); status("demo-status", demoCopy().responding);
  try {
    const data=await api("/api/turn", {method:"POST", headers:{"Content-Type":"application/json","Accept":"application/x-ndjson"}, body:JSON.stringify({session_id:state.sessionId, ...input, language:state.demoLanguage, ...(receipt ? {recap_delivery_id:receipt} : {})})});
    if(generation!==state.generation || demoEpoch!==state.demoEpoch || session!==state.sessionId || !state.connected) return;
    if (["et","en","ru"].includes(data.language)) state.replyLanguage=data.language;
    const heard=addMessage(demoCopy().you, data.text_heard || (data.input_status === "stt_unavailable" ? demoCopy().heardFailed : demoCopy().heardNothing));
    const message=data._stream?.replyNode || addMessage(demoCopy().assistant, data.reply);
    if(data._stream) $("demo-messages").insertBefore(heard,message);
    renderTurnDiagnostics(data);
    renderVoiceResult(data);
    $("demo-text").value="";
    const completedWrite=(data.booking_changes || []).some(change=>["confirmed","cancelled"].includes(change.action));
    const copy=demoCopy(), outcome=copy.outcome;
    const result=data.outcome === "tools_failed" && completedWrite ? outcome.secondaryFailed : outcome[data.outcome] || outcome.ok;
    const expiry=state.demoLanguage === "en" ? ` Turn ${data.turn_count || 1}; conversation expires in ${data.expires_in_s || 0} s.` : ` Voor ${data.turn_count || 1}; vestlus aegub ${data.expires_in_s || 0} s pärast.`;
    status("demo-status", result + (data.tts_failed ? " " + copy.textFallback : "") + expiry, ["tools_failed","unknown_outcome","tts_failed"].includes(data.outcome) ? "error" : "");
    if (data.input_status === "stt_unavailable") status("demo-status", copy.sttFailed,"error");
    else if (data.input_status === "no_speech") status("demo-status", copy.noSpeech,"stale");
    const recap=renderRecap(data,message,data._stream?.receivedAt);
    if(data._stream) finishStreamPlayback(data,recap); else playReply(data,recap);
    const change=(data.booking_changes || []).find(item=>item.kind==="table" && ["confirmed","cancelled"].includes(item.action) && /^\d{4}-\d{2}-\d{2}$/.test(item.date) && /^table_[a-f0-9]{32}$/.test(item.id));
    if(change) { $("booking-date").value=change.date; void changeView(1,change.action==="confirmed" ? change.id : null); }
    else void loadBookings(true);
    void loadCalls();
  } catch(error) {
    if(error.name!=="AbortError" && generation===state.generation && demoEpoch===state.demoEpoch && state.connected) { status("demo-status", demoError(error) + " " + demoCopy().noRetry, "error"); if(error.status===410 || error.status===404) state.sessionId=null; }
  } finally { if(generation===state.generation && demoEpoch===state.demoEpoch) { state.turnBusy=false; controls(); } }
}
async function endDemo() {
  if(!state.sessionId || state.demoEnding) return;
  stopMic(); stopAudio(); state.micStarting=false;
  const id=state.sessionId, generation=state.generation, demoEpoch=++state.demoEpoch; state.turnBusy=state.demoEnding=true; controls();
  try { await api("/api/demo/session/"+encodeURIComponent(id), {method:"DELETE"}); if(generation!==state.generation || demoEpoch!==state.demoEpoch || id!==state.sessionId || !state.connected) return; state.sessionId=null; $("demo-messages").replaceChildren(); status("demo-status", demoCopy().ended); void loadHistory(); }
  catch(error) {
    if(error.name!=="AbortError" && generation===state.generation && demoEpoch===state.demoEpoch && id===state.sessionId && state.connected) {
      if(error.status===410 || error.status===404) {
        state.sessionId=null;
        status("demo-status", demoCopy().expired, "error");
      } else status("demo-status", demoError(error),"error");
    }
  }
  finally { if(generation===state.generation && demoEpoch===state.demoEpoch) { state.turnBusy=state.demoEnding=false; controls(); } }
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
  if (!frames) throw new Error(demoCopy().micEmpty);
  const Offline=window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const offline=new Offline(1,frames,16000), buffer=offline.createBuffer(1,count,mic.context.sampleRate);
  buffer.copyToChannel(input,0);
  const source=offline.createBufferSource(); source.buffer=buffer; source.connect(offline.destination); source.start();
  const rendered=await offline.startRendering(); return encodeWav(rendered.getChannelData(0));
}
async function toggleMic() {
  if(state.mic) {
    const mic=stopMic(), generation=state.generation, session=state.sessionId, micEpoch=state.micEpoch;
    if (!mic.frames || mic.peak < 0.00001) { status("demo-status", demoCopy().micSilent,"error"); return; }
    state.micStarting=true; controls();
    try { const audio=await wav(mic); if(generation===state.generation && session===state.sessionId && micEpoch===state.micEpoch && state.connected) { state.micStarting=false; await sendTurn({audio_b64:audio}); } }
    catch(error) { if(generation===state.generation && micEpoch===state.micEpoch) status("demo-status", demoCopy().micEncoding + " " + error.message,"error"); }
    finally { if(generation===state.generation && micEpoch===state.micEpoch) { state.micStarting=false; controls(); } }
    return;
  }
  if(state.turnBusy || state.micStarting || !requireDemoConnection()) return;
  const generation=state.generation, micEpoch=state.micEpoch;
  if(!state.sessionId) { await startDemo(); if(state.playback && $("demo-audio").src && $("demo-audio").paused===false && !$("demo-audio").ended) return; }
  if(generation!==state.generation || micEpoch!==state.micEpoch || !state.connected || !state.sessionId || state.turnBusy || state.micStarting || document.hidden) return;
  const session=state.sessionId;
  let stream=null, context=null;
  stopAudio(true);
  state.micStarting=true; controls(); status("demo-status", demoCopy().micPermission);
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    if(generation!==state.generation || session!==state.sessionId || micEpoch!==state.micEpoch || state.mic || state.turnBusy || document.hidden) { stream.getTracks().forEach(track=>track.stop()); return; }
    $("demo-audio").pause();
    context=new (window.AudioContext || window.webkitAudioContext)();
    const source=context.createMediaStreamSource(stream), processor=context.createScriptProcessor(4096,1,1), gain=context.createGain(); gain.gain.value=0;
    const mic={stream,context,source,processor,gain,chunks:[],frames:0,peak:0,speechFrames:0,silenceFrames:0,endpointingMs:state.endpointingMs}; state.mic=mic;
    // ponytail: energy endpointing, not semantic VAD; manual stop and 15s cap remain.
    processor.onaudioprocess=event=>{
      if(state.mic!==mic)return;
      const chunk=event.inputBuffer.getChannelData(0), remaining=Math.max(0,Math.floor(context.sampleRate*15)-mic.frames), kept=chunk.subarray(0,remaining);
      mic.chunks.push(new Float32Array(kept)); mic.frames+=kept.length;
      let energy=0; for(const sample of kept) { energy+=sample*sample; mic.peak=Math.max(mic.peak,Math.abs(sample)); }
      const rms=Math.sqrt(energy/Math.max(1,kept.length)), level=Math.min(1,rms*5); $("mic-level").value=level;
      $("mic-feedback-text").textContent=`${Math.floor(mic.frames/context.sampleRate)} / 15 s. ` + (level < .005 ? demoCopy().micQuiet : demoCopy().micSignal);
      if(rms>=.008) { mic.speechFrames+=kept.length; mic.silenceFrames=0; } else mic.silenceFrames+=kept.length;
      if(mic.frames>=Math.floor(context.sampleRate*15) || (mic.speechFrames>=context.sampleRate*.2 && mic.silenceFrames>=context.sampleRate*mic.endpointingMs/1000)) toggleMic();
    };
    source.connect(processor); processor.connect(gain); gain.connect(context.destination); await context.resume();
    if(generation!==state.generation || micEpoch!==state.micEpoch || state.mic!==mic) return;
    mic.timer=setTimeout(()=>{if(state.mic===mic)toggleMic();},15000);
    $("demo-mic").textContent=demoCopy().micStop; status("demo-status", demoCopy().micListening);
    presentation();
  } catch(_) {
    const current=generation===state.generation && micEpoch===state.micEpoch;
    if(state.mic?.stream===stream) stopMic();
    else { stream?.getTracks().forEach(track=>track.stop()); context?.close().catch(()=>{}); }
    if(current) status("demo-status", demoCopy().micDenied,"error");
  } finally {
    if(generation===state.generation && session===state.sessionId && micEpoch===state.micEpoch) { state.micStarting=false; controls(); }
  }
}
async function changeView(page=1, highlightId=null) {
  state.view++; state.page=page; state.highlightId=highlightId; state.bookings=[]; state.fetchedAt=null; state.hasMore=false; state.bookingError=false; renderBookings();
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
$("demo-language").addEventListener("change",changeDemoLanguage);
$("demo-voice").addEventListener("change",changeDemoVoice);
$("demo-form").addEventListener("submit", event=>{event.preventDefault(); const text=$("demo-text").value.trim(); if(text) { stopMic(); sendTurn({text}); }});
$("demo-mic").addEventListener("click",toggleMic);
$("demo-recap-read").addEventListener("click",()=>{const recap=state.recap;if(currentRecap(recap) && !state.turnBusy) { $("demo-audio").pause(); acknowledgeRecap(recap); controls(); $("demo-text").focus(); }});
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
localizeDemo();
controls();

function dayAfter(day, days=1) { return new Date(Date.parse(day+"T12:00:00Z")+days*86400000).toISOString().slice(0,10); }
function renderTurnDiagnostics(data) {
  const messages=state.demoLanguage === "en" ? {transcription_unavailable:"Speech recognition is unavailable. Type a message or check the speech service.",reply_provider_unavailable:"The reply service did not respond. A fallback reply was used; check the server configuration.",reply_provider_fallback:"A fallback reply service was used.",reply_audio_unavailable:"Reply audio could not be created. The text is still here; check the speech service."} : {transcription_unavailable:"Heli transkriptsioon ei ole praegu saadaval. Proovi tekstiga või kontrolli kõnetuvastuse seadistust.",reply_provider_unavailable:"Vastuse mudel ei vastanud. Kasutati varuvastust; kontrolli serveri mudeliseadistust.",reply_provider_fallback:"Vastuseks kasutati varumudelit.",reply_audio_unavailable:"Vastuse heli ei saanud luua. Vastus on tekstina alles; kontrolli kõnesünteesi seadistust."};
  const causes=state.demoLanguage === "en" ? {rate_limited:"The reply service reached its usage limit. Check the limits; do not repeat booking confirmation before checking the booking system.",request_rejected:"The reply service rejected the request. Check the server configuration.",transport_error:"The reply service could not be reached. Check the server connection.",completion_incomplete:"The reply was incomplete. Do not repeat confirmation before checking the booking system.",invalid_response:"The reply service returned an invalid response. This does not confirm booking success."} : {rate_limited:"Vastuse mudeli kasutuslimiit sai täis. Kontrolli mudeliteenuse limiite; ära korda broneeringu kinnitust enne taustsüsteemi kontrolli.",request_rejected:"Mudeliteenus lükkas vastusepäringu tagasi. Kontrolli serveri mudeliseadistust.",transport_error:"Ühendus vastuse mudeliga ebaõnnestus. Kontrolli serveri ühendust mudeliteenusega.",completion_incomplete:"Mudeli vastus jäi pooleli. Ära korda broneeringu kinnitust enne taustsüsteemi kontrolli.",invalid_response:"Mudeliteenus tagastas vigase vastuse. Broneeringu edu ei saa selle vastuse põhjal kinnitada."};
  const warnings=(data.warnings || []).map(item=>item.stage==="llm" && item.code==="reply_provider_unavailable" ? causes[item.cause] || messages[item.code] : messages[item.code]).filter(Boolean);
  if(data.tts_failed && !warnings.some(item=>item===messages.reply_audio_unavailable)) warnings.push(messages.reply_audio_unavailable);
  $("demo-warning").textContent=warnings.join(" "); $("demo-warning").hidden=warnings.length===0;
  const timings=data.timings_ms || {}, labels=state.demoLanguage === "en" ? {stt:"Speech recognition",llm:"Reply",tools:"Booking tools",tts:"Speech synthesis",total:"Total"} : {stt:"Kõnetuvastus",llm:"Vastus",tools:"Broneerimistööriistad",tts:"Kõnesüntees",total:"Kokku"};
  const values=Object.entries(labels).filter(([key])=>Number.isFinite(timings[key])).map(([key,label])=>`${label}: ${(timings[key]/1000).toFixed(1)} s`);
  $("demo-timings").textContent=values.join(" · "); $("demo-timings").hidden=values.length===0;
}
function tableRulesText(rules) {
  const labels={timezone:"Ajavöönd",opening_time:"Avatud alates",closing_time:"Suletud alates",duration_minutes:"Laua kasutusaeg (min)",min_party_size:"Vähim inimeste arv",max_party_size:"Suurim inimeste arv",horizon_days:"Broneerimine ette (päeva)",combine_tables:"Lauad ühendatavad",children_count_toward_party_size:"Lapsed arvestatakse inimeste hulka"};
  return Object.entries(rules).filter(([,value])=>["string","number","boolean"].includes(typeof value)).map(([key,value])=>`${labels[key] || key}: ${typeof value==="boolean" ? value?"jah":"ei" : value}`).join(" · ");
}
function bookingControls() {
  const locked=!state.connected || bookingUi.busy;
  for(const id of ["new-table-date","new-start-time","new-party-size","booking-decline","booking-cancel-decline"]) $(id).disabled=locked;
  $("booking-search").disabled=locked || bookingUi.uncertain;
    $("booking-recap-read").disabled=locked || bookingUi.uncertain || !bookingUi.holdId || !bookingUi.recapDeliveryId || bookingUi.acknowledged;
    $("booking-recap-read").hidden=bookingUi.acknowledged;
  $("booking-confirm").disabled=locked || bookingUi.uncertain || !bookingUi.holdId || !bookingUi.acknowledged;
  for(const id of ["booking-cancel-request","booking-cancel"]) $(id).disabled=locked || bookingUi.uncertain || !bookingUi.confirmed;
  for(const button of document.querySelectorAll?.(".offer-button") || []) button.disabled=locked || bookingUi.uncertain;
}
function resetBookingUi() {
  Object.assign(bookingUi,{sessionId:null,busy:false,uncertain:false,holdId:null,recapDeliveryId:null,acknowledged:false,selected:null,confirmed:null,tables:[],rules:null,epoch:bookingUi.epoch+1});
  $("booking-offers").replaceChildren(); $("table-rules").textContent="";
  $("booking-recap").hidden=true; $("booking-receipt").hidden=true; $("booking-cancel-actions").hidden=true;
  $("booking-recap-text").textContent=""; $("booking-receipt-text").textContent="";
  status("new-booking-status","Ühenda töölaud, et kontrollida saadavust ja teha testbroneering.");
}
function clearBookingSelection() {
  bookingUi.epoch++; bookingUi.holdId=null; bookingUi.recapDeliveryId=null; bookingUi.acknowledged=false; bookingUi.selected=null;
  $("booking-offers").replaceChildren(); $("booking-recap").hidden=true;
  $("booking-recap-text").textContent="";
  bookingControls();
}
function bookingRequestValid() {
  const count=$("new-party-size").value;
  return /^\d{4}-\d{2}-\d{2}$/.test($("new-table-date").value) && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test($("new-start-time").value) && /^[1-9]\d*$/.test(count) && Number(count)<=(bookingUi.rules?.max_party_size || 6);
}
async function searchBooking() {
  if(!state.connected || bookingUi.busy || bookingUi.uncertain) return;
  if(!bookingRequestValid()) { status("new-booking-status","Vali kuupäev, täpne Tallinna kellaaeg ja lubatud täisarv inimesi, ka lapsed.","error"); return; }
  clearBookingSelection(); bookingUi.busy=true; controls();
  const generation=state.generation, epoch=bookingUi.epoch;
  status("new-booking-status","Kontrollin saadavust taustsüsteemist…");
  try {
    if(!bookingUi.sessionId) { const session=await api("/api/booking/session",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}); if(generation!==state.generation) return; bookingUi.sessionId=session.session_id; }
    const input={date:$("new-table-date").value,start_time:$("new-start-time").value,party_size:Number($("new-party-size").value)};
    const data=await api("/api/booking/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:bookingUi.sessionId,kind:bookingUi.kind,...input})});
    if(generation!==state.generation || epoch!==bookingUi.epoch || !state.connected) return;
    if(data.kind!=="table" || !Array.isArray(data.offers)) throw new Error("Restorani saadavuse vastus ei olnud loetav. Broneeringut ei loodud.");
    const offers=data.offers;
    for(const offer of offers) {
      const button=document.createElement("button"), title=document.createElement("strong"), note=document.createElement("span"); button.type="button"; button.className="offer-button";
      title.textContent=`${offer.date} · ${offer.start_time} · ${offer.party_size} inimest`;
      note.textContent=`${offer.table_name || offer.table_id} · kuni ${offer.capacity} inimest · ${offer.duration_minutes} min · vali ja loe kokkuvõte`;
      button.append(title,note); button.addEventListener("click",()=>prepareBooking(offer)); $("booking-offers").append(button);
    }
    status("new-booking-status",offers.length?"Vali sobiv pakkumine. Broneering tekib pärast kokkuvõtte kinnitamist.":"Sellele valikule saadavust ei leitud. Proovi teist kuupäeva või külaliste arvu.");
  } catch(error) { if(error.name!=="AbortError" && generation===state.generation && state.connected) { status("new-booking-status",error.message,"error"); if(error.status===410 || error.status===404) bookingUi.sessionId=null; } }
  finally { if(generation===state.generation) { bookingUi.busy=false; controls(); } }
}
async function prepareBooking(offer) {
  if(!state.connected || bookingUi.busy || bookingUi.uncertain) return;
  bookingUi.epoch++; bookingUi.busy=true; bookingUi.holdId=null; bookingUi.recapDeliveryId=null; bookingUi.acknowledged=false; bookingUi.selected={...offer,kind:"table"};
  $("booking-recap").hidden=true; $("booking-recap-text").textContent=""; controls();
  const generation=state.generation, epoch=bookingUi.epoch;
  try {
    const selection={table_offer_id:offer.table_offer_id};
    const data=await api("/api/booking/prepare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:bookingUi.sessionId,kind:bookingUi.kind,guest_fixture_id:"guest-001",...selection})});
    if(generation!==state.generation || epoch!==bookingUi.epoch || !state.connected) return;
    const recap=typeof data.recap_text==="string" ? data.recap_text : data.recap;
    if(data.kind!=="table" || typeof data.hold_id!=="string" || !data.hold_id || typeof recap!=="string" || !recap.trim() || !/^[a-f0-9]{32}$/.test(data.recap_delivery_id || "")) throw new Error("Täpne kokkuvõte või selle lugemise viide puudub. Kinnitamist ei avatud.");
    bookingUi.holdId=data.hold_id; bookingUi.recapDeliveryId=data.recap_delivery_id;
    $("booking-recap-text").textContent=recap; $("booking-recap").hidden=false;
    status("new-booking-status","Loe täpne kokkuvõte läbi ja märgi see loetuks. See ei kinnita veel broneeringut.");
  } catch(error) { if(error.name!=="AbortError" && generation===state.generation && epoch===bookingUi.epoch && state.connected) status("new-booking-status",error.message,"error"); }
  finally { if(generation===state.generation) { bookingUi.busy=false; controls(); if(epoch===bookingUi.epoch && bookingUi.holdId) $("booking-recap-read").focus(); } }
}
async function acknowledgeBookingRecap() {
  if(!state.connected || bookingUi.busy || bookingUi.uncertain || !bookingUi.holdId || !bookingUi.recapDeliveryId || bookingUi.acknowledged) return;
  const generation=state.generation, epoch=bookingUi.epoch, hold=bookingUi.holdId, receipt=bookingUi.recapDeliveryId;
  bookingUi.busy=true; bookingUi.recapDeliveryId=null; controls();
  try {
    // The exact preparation's one-use receipt is separate from later consent.
    const data=await api("/api/booking/recap",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:bookingUi.sessionId,hold_id:hold,recap_delivery_id:receipt})});
    if(generation!==state.generation || epoch!==bookingUi.epoch || hold!==bookingUi.holdId || !state.connected) return;
    if(data.acknowledged!==true || data.hold_id!==hold) throw new Error("Kokkuvõtte lugemist ei kinnitatud. Valmista pakkumine uuesti ette.");
    bookingUi.acknowledged=true;
    status("new-booking-status","Kokkuvõte märgiti loetuks. Broneerimiseks vajuta „Jah, kinnitan broneeringu” või loobu.");
  } catch(error) { if(error.name!=="AbortError" && generation===state.generation && epoch===bookingUi.epoch && state.connected) status("new-booking-status",error.message+" Kinnitamine jääb suletuks; valmista pakkumine uuesti ette.","error"); }
  finally { if(generation===state.generation) { bookingUi.busy=false; controls(); if(epoch===bookingUi.epoch) $(bookingUi.acknowledged?"booking-confirm":"booking-search").focus(); } }
}
async function mutateBooking(action) {
  if(!["confirm","cancel"].includes(action) || !state.connected || bookingUi.busy || bookingUi.uncertain || (action==="confirm" && (!bookingUi.holdId || !bookingUi.acknowledged)) || (action==="cancel" && (!bookingUi.confirmed || $("booking-cancel-actions").hidden))) return;
  bookingUi.busy=true; controls();
  const generation=state.generation;
  let completed=false;
  status("new-booking-status",action==="confirm"?"Kinnitan testbroneeringut…":"Tühistan testbroneeringut…");
  try {
    const kind=action==="confirm"?bookingUi.kind:bookingUi.confirmed.kind;
    const selection=action==="confirm"?{hold_id:bookingUi.holdId}:{booking_id:bookingUi.confirmed.id};
    const data=await api("/api/booking/"+action,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:bookingUi.sessionId,kind,consent:true,...selection})});
    if(generation!==state.generation || !state.connected) return;
    if(data.outcome==="unknown_outcome" || data.unknown_outcome) { bookingUi.uncertain=true; throw new Error("Toimingu tulemus on ebaselge. Ära korda kinnitamist ega tühistamist. Kontrolli broneeringute ülevaadet."); }
    if(data.ok!==true || data.kind!=="table") throw new Error("Restorani taustsüsteem ei kinnitanud toimingu õnnestumist.");
    if(action==="confirm") {
      const receipt=data.booking || {}, id=String(data.booking_id || receipt.id || "");
      if(!/^table_[a-f0-9]{32}$/.test(id)) { bookingUi.uncertain=true; throw new Error("Restorani broneeringu viide puudub või ei sobi. Kontrolli taustsüsteemi enne uut toimingut."); }
      bookingUi.confirmed={kind,id}; bookingUi.holdId=null; bookingUi.recapDeliveryId=null; bookingUi.acknowledged=false;
      $("booking-recap").hidden=true; $("booking-offers").replaceChildren(); $("booking-receipt").hidden=false; $("booking-cancel-request").hidden=false;
      $("booking-receipt-title").textContent="Testbroneering on kinnitatud"; $("booking-receipt-text").textContent="Taustsüsteemi viide: "+id;
      completed=true;
      $("booking-cancel-actions").hidden=true;
      const day=receipt.date || bookingUi.selected?.date;
      if(/^\d{4}-\d{2}-\d{2}$/.test(day || "")) { $("booking-date").value=day; void changeView(1,id); }
      else void loadBookings(true);
      if(generation!==state.generation || !state.connected) return;
      status("new-booking-status",state.bookingError?"Kinnitusviide saadi, kuid sõltumatu lugemine ebaõnnestus. Ära korda kinnitamist; uuenda ülevaadet.":"Kinnitus tuli taustsüsteemist. Kontrolli sõltumatu ülevaate olekut ja broneeringuviidet.",state.bookingError?"stale":"");
    } else {
      bookingUi.confirmed=null; $("booking-cancel-request").hidden=true; $("booking-cancel-actions").hidden=true;
      $("booking-receipt-title").textContent="Testbroneering on tühistatud"; status("new-booking-status","Taustsüsteem kinnitas tühistamise.");
      completed=true;
      void loadBookings(true);
    }
  } catch(error) {
    if(error.name!=="AbortError" && generation===state.generation && state.connected) {
      if(!error.status || error.status>=500 || ["mutation_outcome_unknown","write_outcome_unknown","cancel_outcome_unknown"].includes(error.code)) bookingUi.uncertain=true;
      status("new-booking-status",error.message+(bookingUi.uncertain?" Tulemust ei korrata automaatselt. Kontrolli broneeringute ülevaadet.":""),"error");
    }
  } finally { if(generation===state.generation) { bookingUi.busy=false; controls(); if(completed) $("booking-receipt-title").focus(); } }
}
$("booking-search-form").addEventListener("submit",event=>{event.preventDefault();searchBooking();});
for(const id of ["new-table-date","new-start-time","new-party-size"]) $(id).addEventListener("change",clearBookingSelection);
$("booking-recap-read").addEventListener("click",acknowledgeBookingRecap);
$("booking-confirm").addEventListener("click",()=>mutateBooking("confirm"));
$("booking-decline").addEventListener("click",()=>{clearBookingSelection();status("new-booking-status","Loobusid pakkumisest. Broneeringut ei loodud.");$("booking-search").focus();});
$("booking-cancel-request").addEventListener("click",()=>{$("booking-cancel-actions").hidden=false;$("booking-cancel").focus();});
$("booking-cancel").addEventListener("click",()=>mutateBooking("cancel"));
$("booking-cancel-decline").addEventListener("click",()=>{$("booking-cancel-actions").hidden=true;$("booking-cancel-request").focus();});
for(const button of document.querySelectorAll?.(".example-button") || []) button.addEventListener("click",()=>sendTurn({text:button.dataset.message}));
$("new-table-date").value=dayAfter(tallinnDay()); $("new-table-date").min=tallinnDay();
if(query.get("book")==="table") location.hash="#new-booking-section";
