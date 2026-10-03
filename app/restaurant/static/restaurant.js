"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  credential: "",
  connected: false,
  generation: 0,
  controllers: new Set(),
  sessionId: null,
  callId: null,
  turnBusy: false,
  audioUrl: null,
  audioEpoch: 0,
  playback: null,
  turnController: null,
  recap: null,
  demoVoice: "azure",
  voiceCatalog: null,
  previewBusy: false,
  endpointingMs: 650,
  mic: null,
  micStarting: false,
  micEpoch: 0,
  recapDeliveryId: null,
  awaitingRecapId: null,
  demoLanguage: "et",
  replyLanguage: "et",
  readBusy: false,
  page: 1,
  hasMore: false,
  restaurant: null,
  voiceReady: false,
  audioReady: false,
  bookingReady: false,
  bookingView: 0,
  latestBooking: null,
};
const reservation = {
  sessionId: null,
  holdId: null,
  bookingId: null,
  acknowledged: false,
  busy: false,
  uncertain: false,
  date: null,
};
const TEXT = {
  voice: ["Abilise hääl", "Assistant voice", "Голос помощника"],
  voicePreview: ["Kuula häält", "Listen to voice", "Послушать голос"],
  voicePreviewLoading: ["Valmistan hääleproovi…", "Preparing voice sample…", "Готовлю образец голоса…"],
  voicePreviewReady: ["Hääleproov on valmis.", "Voice sample is ready.", "Образец голоса готов."],
  voicePreviewFailed: [
    "Hääleproovi ei saanud luua. Proovi uuesti või vali teine hääl.",
    "Could not prepare the voice sample. Try again or choose another voice.",
    "Не удалось подготовить образец. Попробуйте ещё раз или выберите другой голос.",
  ],
  voiceSelectorHelp: [
    "Vali ja kuula häält enne vestlust. Rahulik variant räägib aeglasemalt.",
    "Choose and listen before starting. The calm option speaks more slowly.",
    "Выберите и послушайте голос до начала разговора. Спокойный вариант говорит медленнее.",
  ],
  voiceFallback: [
    "Kasutati varuhäält",
    "Fallback voice used",
    "Использован резервный голос",
  ],
  endReservation: [
    "Lõpeta broneerimisvestlus",
    "End reservation session",
    "Завершить сеанс бронирования",
  ],
  bookingMissing: [
    "Lauabroneeringute teenus pole aktiveeritud.",
    "Table reservations are not enabled.",
    "Бронирование столиков не включено.",
  ],
  guests: ["külalist", "guests", "гостей"],
  reservationReady: [
    "Vali laua kuupäev, saabumisaeg ja külaliste koguarv.",
    "Choose the table date, arrival time and total guest count.",
    "Выберите дату, время прибытия и общее число гостей.",
  ],
  browserConversation: [
    "Veebivestlus",
    "Browser conversation",
    "Разговор в браузере",
  ],
  telephoneConversation: [
    "Telefonikõne",
    "Telephone call",
    "Телефонный звонок",
  ],
  messages: ["sõnumit", "messages", "сообщений"],
  completed: ["Lõpetatud", "Completed", "Завершено"],
  needsAttention: [
    "Vajab kontrollimist",
    "Needs attention",
    "Требует проверки",
  ],
  active: ["Pooleli", "In progress", "В процессе"],
  booked: ["kinnitatud", "confirmed", "подтверждено"],
  cancelledState: ["tühistatud", "cancelled", "отменено"],
  skip: ["Hüppa sisu juurde", "Skip to content", "Перейти к содержимому"],
  brand: ["Restorani vastuvõtt", "Restaurant reception", "Ресепшн ресторана"],
  title: [
    "Restorani kõneabiline",
    "Your restaurant voice assistant",
    "Голосовой помощник ресторана",
  ],
  intro: [
    "Üks abiline laua leidmiseks ja külaliste küsimustele vastamiseks.",
    "One assistant for finding a table and answering your guests' questions.",
    "Один помощник для бронирования столика и ответов на вопросы гостей.",
  ],
  language: [
    "Vali vestluse keel",
    "Choose your conversation language",
    "Выберите язык разговора",
  ],
  languageHelp: [
    "Abiline alustab ja vastab valitud keeles.",
    "The assistant starts and replies in your chosen language.",
    "Помощник начинает разговор и отвечает на выбранном языке.",
  ],
  languageLocked: [
    "Keele vahetamiseks lõpeta pooleliolev vestlus.",
    "End the active conversation before changing language.",
    "Завершите текущий разговор перед сменой языка.",
  ],
  demo: [
    "Fiktiivne restoranidemo.",
    "Fictional restaurant demo.",
    "Демонстрация вымышленного ресторана.",
  ],
  demoNotice: [
    "Kasuta ainult näidiskülalisi. Broneeringud ei anna õigust päris külastusele.",
    "Use fictional guests only. Reservations do not entitle you to a real visit.",
    "Используйте только тестовых гостей. Бронирование не даёт права на настоящее посещение.",
  ],
  connectTitle: [
    "Ühenda töölaud",
    "Connect your workspace",
    "Подключите рабочее пространство",
  ],
  connectHelp: [
    "Operaatori tunnus avab lauabroneeringud ja kõneproovi.",
    "Your operator token opens table reservations and the voice demo.",
    "Токен оператора открывает бронирования столиков и голосовую демонстрацию.",
  ],
  token: ["Operaatori tunnus", "Operator token", "Токен оператора"],
  connect: ["Ühenda", "Connect", "Подключить"],
  logout: ["Lõpeta ühendus", "Disconnect", "Отключиться"],
  tokenHelp: [
    "Tunnust hoitakse ainult selle lehe mälus.",
    "The token is kept only in this page's memory.",
    "Токен хранится только в памяти этой страницы.",
  ],
  voiceTitle: [
    "Proovi kõneabilist",
    "Try the voice assistant",
    "Попробуйте голосового помощника",
  ],
  voiceHelp: [
    "Küsi laua, menüü või lahtiolekuaegade kohta.",
    "Ask about a table, the menu or opening hours.",
    "Спросите о столике, меню или часах работы.",
  ],
  voiceBadge: ["Tekst ja mikrofon", "Text and microphone", "Текст и микрофон"],
  start: ["Alusta vestlust", "Start conversation", "Начать разговор"],
  end: ["Lõpeta vestlus", "End conversation", "Завершить разговор"],
  signIn: [
    "Ühenda esmalt operaatori tunnusega.",
    "Connect with your operator token first.",
    "Сначала подключитесь с токеном оператора.",
  ],
  exampleTable: ["Lauabroneering", "Table reservation", "Бронирование столика"],
  exampleMenu: ["Menüü", "Menu", "Меню"],
  exampleHours: ["Lahtiolekuajad", "Opening hours", "Часы работы"],
  message: ["Sõnum abilisele", "Message the assistant", "Сообщение помощнику"],
  send: ["Saada", "Send", "Отправить"],
  placeholder: [
    "Näiteks: soovin homseks lauda nelja inimesega kell 19.00",
    "For example: a table for four tomorrow at 19:00",
    "Например: столик на четверых завтра в 19:00",
  ],
  transcript: [
    "Selle lehe vestlus",
    "Conversation on this page",
    "Разговор на этой странице",
  ],
  audio: ["Abilise vastus", "Assistant's reply", "Ответ помощника"],
  micStart: [
    "Alusta häälvestlust",
    "Start voice conversation",
    "Начать голосовой разговор",
  ],
  micReady: [
    "Luba mikrofon ja räägi",
    "Enable your microphone and speak",
    "Включите микрофон и говорите",
  ],
  micStop: [
    "Lõpeta ja saada heli",
    "Stop and send audio",
    "Остановить и отправить аудио",
  ],
  micLevel: ["Mikrofoni helitase", "Microphone level", "Уровень микрофона"],
  micHelp: [
    "Räägi loomulikult. Kõnepaus saadab heli; teine vajutus saadab kohe. Üks salvestis kestab kuni 15 sekundit.",
    "Speak naturally. A pause sends your audio; press again to send immediately. Each recording lasts up to 15 seconds.",
    "Говорите естественно. Пауза отправляет аудио; повторное нажатие отправляет сразу. Запись длится до 15 секунд.",
  ],
  consentTitle: [
    "Kuidas kinnitamine töötab?",
    "How does confirmation work?",
    "Как работает подтверждение?",
  ],
  recapRead: [
    "Olen kokkuvõtte läbi lugenud",
    "I have read the recap",
    "Я прочитал(а) итог",
  ],
  reservationTitle: [
    "Broneeri laud",
    "Reserve a table",
    "Забронировать столик",
  ],
  reservationHelp: [
    "Vali kuupäev, saabumisaeg ja külaliste koguarv.",
    "Choose a date, arrival time and total number of guests.",
    "Выберите дату, время прибытия и общее число гостей.",
  ],
  date: ["Kuupäev", "Date", "Дата"],
  time: ["Saabumisaeg", "Arrival time", "Время прибытия"],
  party: [
    "Külalisi koos lastega",
    "Guests including children",
    "Гостей, включая детей",
  ],
  prepare: ["Kontrolli lauda", "Check for a table", "Проверить столик"],
  reservationInitial: [
    "Ühenda, et proovida lauabroneeringut.",
    "Connect to try a table reservation.",
    "Подключитесь, чтобы попробовать бронирование.",
  ],
  recapTitle: ["Kontrolli kokkuvõtet", "Review your recap", "Проверьте итог"],
  confirm: [
    "Kinnita lauabroneering",
    "Confirm table reservation",
    "Подтвердить бронирование",
  ],
  cancel: [
    "Tühista see broneering",
    "Cancel this reservation",
    "Отменить это бронирование",
  ],
  capacityHelp: [
    "Suure grupi ja erisoovid peab kinnitama personal.",
    "Staff must confirm large groups and special requests.",
    "Большие группы и особые пожелания подтверждает персонал.",
  ],
  bookingsTitle: [
    "Lauabroneeringud",
    "Table reservations",
    "Бронирования столиков",
  ],
  bookingsHelp: [
    "Demo kõnes ja siin kinnitatud lauad ilmuvad sellesse loendisse.",
    "Tables confirmed in the demo conversation or here appear in this list.",
    "Столики, подтверждённые в демонстрационном разговоре или здесь, появляются в этом списке.",
  ],
  viewBooking: ["Vaata broneeringut", "View reservation", "Посмотреть бронь"],
  refresh: ["Uuenda", "Refresh", "Обновить"],
  private: [
    "Andmed on privaatsed. Ühenda esmalt.",
    "This information is private. Connect first.",
    "Это частные данные. Сначала подключитесь.",
  ],
  previous: ["Eelmine", "Previous", "Назад"],
  next: ["Järgmine", "Next", "Далее"],
  infoTitle: [
    "Restorani teave",
    "Restaurant information",
    "Информация о ресторане",
  ],
  menuTitle: ["Menüü", "Menu", "Меню"],
  hoursTitle: ["Lahtiolekuajad", "Opening hours", "Часы работы"],
  historyTitle: ["Kõneajalugu", "Call history", "История звонков"],
  historyHelp: [
    "Salvestatakse tehnilised sündmused ja toimingute tulemused, mitte heli ega vestluse sisu.",
    "History stores technical events and action results. Audio and conversation content are not stored.",
    "История хранит технические события и результаты действий. Аудио и содержание разговора не сохраняются.",
  ],
  footer: [
    "Restorani demo · Eesti, English, Русский",
    "Restaurant demo · Eesti, English, Русский",
    "Демонстрация ресторана · Eesti, English, Русский",
  ],
  disconnected: ["Ühendamata", "Disconnected", "Не подключено"],
  connected: ["Ühendatud", "Connected", "Подключено"],
  loading: ["Laadin…", "Loading…", "Загрузка…"],
  failed: [
    "Toiming ebaõnnestus. Kontrolli ühendust või proovi hiljem uuesti.",
    "The request failed. Check your connection or try again later.",
    "Запрос не удался. Проверьте подключение или попробуйте позже.",
  ],
  authFailed: [
    "Tunnus ei sobi või teenus pole saadaval.",
    "The token was rejected or the service is unavailable.",
    "Токен отклонён или сервис недоступен.",
  ],
  empty: [
    "Selleks päevaks lauabroneeringuid ei ole.",
    "There are no table reservations for this date.",
    "На эту дату бронирований столиков нет.",
  ],
  noHistory: [
    "Kõnesid veel ei ole.",
    "No conversations yet.",
    "Разговоров пока нет.",
  ],
  ready: [
    "Vestlus valmis. Kirjuta või räägi mikrofoniga.",
    "Conversation ready. Type or speak into your microphone.",
    "Разговор готов. Напишите или говорите в микрофон.",
  ],
  responding: [
    "Abiline vastab…",
    "The assistant is replying…",
    "Помощник отвечает…",
  ],
  you: ["Sina", "You", "Вы"],
  assistant: [
    "Restorani abiline",
    "Restaurant assistant",
    "Помощник ресторана",
  ],
  ended: [
    "Vestlus lõpetatud. Võid valida teise keele.",
    "Conversation ended. You can choose another language.",
    "Разговор завершён. Можно выбрать другой язык.",
  ],
  textFallback: [
    "Heli pole saadaval; tekst on alles.",
    "Audio is unavailable; the text is still available.",
    "Аудио недоступно; текст сохранён на странице.",
  ],
  noRetry: [
    "Ära korda võimalikku kinnitust; kontrolli broneeringute loendit.",
    "Do not repeat a possible confirmation; check the reservation list.",
    "Не повторяйте возможное подтверждение; проверьте список бронирований.",
  ],
  acknowledged: [
    "Kokkuvõte loetud. Nüüd saad eraldi kinnitada.",
    "Recap read. You can now confirm separately.",
    "Итог прочитан. Теперь можно отдельно подтвердить.",
  ],
  confirmed: [
    "Testbroneering kinnitatud.",
    "Test reservation confirmed.",
    "Тестовое бронирование столика подтверждено.",
  ],
  cancelled: [
    "Testbroneering tühistatud.",
    "Test reservation cancelled.",
    "Тестовое бронирование столика отменено.",
  ],
  unknown: [
    "Tulemus on ebaselge. Ära korda toimingut; palu personalil kontrollida.",
    "The result is uncertain. Do not repeat the action; ask staff to check.",
    "Результат неизвестен. Не повторяйте действие; попросите персонал проверить.",
  ],
  unavailable: [
    "Soovitud ajal sobivat lauda ei ole. Proovi teist aega või kuupäeva.",
    "No suitable table is available at that time. Try another time or date.",
    "На это время подходящего столика нет. Попробуйте другое время или дату.",
  ],
  micPermission: [
    "Ootan mikrofoni luba…",
    "Waiting for microphone permission…",
    "Ожидание разрешения микрофона…",
  ],
  micListening: [
    "Kuulan… räägi ja tee siis paus.",
    "Listening… speak, then pause.",
    "Слушаю… говорите, затем сделайте паузу.",
  ],
  micSilent: [
    "Salvestises ei tuvastatud heli. Kontrolli mikrofoni.",
    "No audio was detected. Check your microphone.",
    "Звук не обнаружен. Проверьте микрофон.",
  ],
  micEmpty: ["Salvestis on tühi.", "The recording is empty.", "Запись пуста."],
  micEncoding: [
    "Heli ettevalmistamine ei õnnestunud.",
    "Audio preparation failed.",
    "Подготовка аудио не удалась.",
  ],
  micDenied: [
    "Mikrofoni ei saanud avada. Kontrolli luba või kirjuta sõnum.",
    "The microphone could not be opened. Check permission or type a message.",
    "Не удалось открыть микрофон. Проверьте разрешение или напишите сообщение.",
  ],
  micQuiet: [
    "Heli on väga vaikne.",
    "The audio is very quiet.",
    "Звук очень тихий.",
  ],
  micSignal: [
    "Mikrofon töötab.",
    "Microphone audio detected.",
    "Микрофон обнаружил звук.",
  ],
  replyPlayed: ["Vastus esitatud.", "Reply played.", "Ответ воспроизведён."],
  audioError: [
    "Heli esitamine ebaõnnestus.",
    "Audio playback failed.",
    "Не удалось воспроизвести аудио.",
  ],
  autoplay: [
    "Vajuta heli esitamiseks mängimisnuppu.",
    "Press play to hear the audio.",
    "Нажмите воспроизведение, чтобы услышать аудио.",
  ],
  audioInvalid: [
    "Vastuse heli pole saadaval.",
    "Reply audio is unavailable.",
    "Аудио ответа недоступно.",
  ],
  closed: ["suletud", "closed", "закрыто"],
  voiceConfigured: [
    "Kõneproovi teenused seadistatud",
    "Voice demo services configured",
    "Сервисы голосовой демонстрации настроены",
  ],
  voiceMissing: [
    "Kõneproovi teenused pole seadistatud",
    "Voice demo services are not configured",
    "Сервисы голосовой демонстрации не настроены",
  ],
};
const DAYS = {
  et: [
    "Esmaspäev",
    "Teisipäev",
    "Kolmapäev",
    "Neljapäev",
    "Reede",
    "Laupäev",
    "Pühapäev",
  ],
  en: [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
  ],
  ru: [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
  ],
};
function uiLanguage() {
  return state.demoLanguage === "auto" ? "et" : state.demoLanguage;
}
function demoCopy() {
  const index = { et: 0, en: 1, ru: 2 }[uiLanguage()];
  return Object.fromEntries(
    Object.entries(TEXT).map(([key, values]) => [key, values[index]]),
  );
}
function status(id, text, kind = "") {
  const element = $(id);
  element.textContent = text;
  element.className = "status " + kind;
}
function tallinnDay(offset = 0) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Tallinn",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = (key) => parts.find((part) => part.type === key).value;
  const date = `${value("year")}-${value("month")}-${value("day")}`;
  return new Date(Date.parse(date + "T12:00:00Z") + offset * 86400000)
    .toISOString()
    .slice(0, 10);
}
function presentation() {
  $("mic-feedback").hidden = !state.mic;
}
function localize() {
  const copy = demoCopy();
  document.documentElement.lang = uiLanguage();
  document.title = copy.title + " · Voicebot";
  for (const element of document.querySelectorAll("[data-copy]"))
    element.textContent = copy[element.dataset.copy];
  for (const element of document.querySelectorAll("[data-placeholder]"))
    element.placeholder = copy[element.dataset.placeholder];
  for (const element of document.querySelectorAll("[data-aria]"))
    element.setAttribute("aria-label", copy[element.dataset.aria]);
  $("connection-state").textContent = state.connected
    ? copy.connected
    : copy.disconnected;
  $("consent-help").textContent = {
    et: "Kuula või loe täpne kokkuvõte. Alles seejärel ütle „Jah, kinnitan.” või vajuta eraldi kinnitamisnuppu. „Jah, tühista.” tühistab ainult selles vestluses loodud broneeringu. Ära sisesta päris kontakte.",
    en: 'Listen to or read the exact recap. Then say "Yes, confirm." or press the separate confirmation button. "Yes, cancel." cancels only a reservation created in this conversation. Do not enter real contacts.',
    ru: "Прослушайте или прочитайте точный итог. Затем скажите «Да, подтверждаю.» или нажмите отдельную кнопку подтверждения. «Да, отмените.» отменяет только бронирование из этого разговора. Не вводите настоящие контакты.",
  }[uiLanguage()];
  renderInformation();
  renderVoices();
  controls();
}
function controls() {
  const locked = state.turnBusy || state.micStarting || state.previewBusy;
  $("connect").disabled = !!state.credential;
  $("logout").disabled = !state.connected;
  $("demo-language").disabled =
    !!state.sessionId ||
    locked ||
    !!state.mic ||
    reservation.busy ||
    !!reservation.sessionId;
  for (const input of $("demo-language").querySelectorAll("input"))
    input.checked = input.value === state.demoLanguage;
  $("language-help").textContent =
    state.sessionId || reservation.sessionId
      ? demoCopy().languageLocked
      : demoCopy().languageHelp;
  $("demo-start").disabled =
    !state.connected || !state.voiceReady || !!state.sessionId || locked;
  $("demo-end").disabled = !state.sessionId || locked;
  $("demo-voice").disabled =
    !state.connected || !!state.sessionId || locked || !!state.mic;
  $("demo-voice-preview").disabled =
    $("demo-voice").disabled || !Array.from($("demo-voice").options).some(
      option => option.value === state.demoVoice && !option.disabled,
    );
  $("demo-voice-preview").textContent = state.previewBusy
    ? demoCopy().voicePreviewLoading : demoCopy().voicePreview;
  for (const id of ["demo-text", "demo-send"])
    $(id).disabled = !state.sessionId || locked;
  $("demo-mic").disabled = !state.connected || !state.audioReady || locked;
  if (!state.mic)
    $("demo-mic").textContent = state.sessionId
      ? demoCopy().micReady
      : demoCopy().micStart;
  $("demo-recap-read").disabled = !currentRecap(state.recap) || locked;
  $("refresh").disabled = !state.connected || state.readBusy;
  $("booking-prev").disabled =
    !state.connected || state.readBusy || state.page <= 1;
  $("booking-next").disabled =
    !state.connected || state.readBusy || !state.hasMore;
  for (const element of $("reservation-form").elements)
    element.disabled =
      !state.connected ||
      !state.bookingReady ||
      reservation.busy ||
      reservation.uncertain ||
      !!reservation.holdId ||
      !!reservation.bookingId;
  $("reservation-read").disabled =
    !reservation.holdId || reservation.busy || reservation.acknowledged;
  $("reservation-confirm").disabled =
    !reservation.holdId ||
    !reservation.acknowledged ||
    reservation.busy ||
    reservation.uncertain;
  $("reservation-cancel").disabled =
    !reservation.bookingId || reservation.busy || reservation.uncertain;
  $("reservation-end").disabled =
    !reservation.sessionId || reservation.busy || reservation.uncertain;
  for (const button of document.querySelectorAll(".example-button"))
    button.disabled = !state.sessionId || locked;
  presentation();
}
function requireDemoConnection() {
  if (state.connected) return true;
  status("demo-status", demoCopy().signIn, "error");
  $("operator-token").focus();
  return false;
}
const VOICE_LABELS = {
  azure: ["Loomulik hääl", "Natural voice", "Естественный голос"],
  "azure-male": ["Kert · meeshääl", "Guy · male voice", "Дмитрий · мужской голос"],
  "azure-calm": ["Anu · rahulik", "Jenny · calm", "Светлана · спокойный"],
  elevenlabs: ["ElevenLabs", "ElevenLabs", "ElevenLabs"],
  google: ["Google Chirp", "Google Chirp", "Google Chirp"],
  cartesia: ["Cartesia Sonic", "Cartesia Sonic", "Cartesia Sonic"],
};
function voiceLabel(id) {
  return VOICE_LABELS[id]?.[["et", "en", "ru"].indexOf(uiLanguage())] || "";
}
function renderVoices() {
  const select = $("demo-voice");
  select.replaceChildren();
  const catalog = state.voiceCatalog || [
    { id: "azure", available: state.voiceReady, languages: ["et", "en", "ru"] },
  ];
  for (const profile of [...catalog].sort((a, b) => Number(b.available) - Number(a.available))) {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = voiceLabel(profile.id);
    option.disabled =
      !profile.available || !profile.languages.includes(uiLanguage());
    select.append(option);
  }
  if (
    !state.sessionId &&
    !Array.from(select.options).some(
      (option) => option.value === state.demoVoice && !option.disabled,
    )
  )
    state.demoVoice = "azure";
  select.value = state.demoVoice;
}
async function loadVoices() {
  const generation = state.generation;
  try {
    const data = await api("/api/demo/voices");
    if (generation !== state.generation || !state.connected) return;
    const ids = new Set();
    if (
      !Array.isArray(data.voices) ||
      data.voices.length > Object.keys(VOICE_LABELS).length ||
      data.voices.some(
        (profile) =>
          !profile ||
          !Object.hasOwn(VOICE_LABELS, profile.id) ||
          ids.has(profile.id) ||
          !ids.add(profile.id) ||
          typeof profile.available !== "boolean" ||
          !Array.isArray(profile.languages) ||
          profile.languages.some(
            (language) => !["et", "en", "ru"].includes(language),
          ),
      ) ||
      !ids.has("azure")
    )
      throw new Error("Invalid voice catalog");
    state.voiceCatalog = data.voices;
    state.endpointingMs =
      Number.isInteger(data.endpointing_ms) &&
      data.endpointing_ms >= 300 &&
      data.endpointing_ms <= 2000
        ? data.endpointing_ms
        : 650;
  } catch (_) {
    if (generation !== state.generation || !state.connected) return;
    state.voiceCatalog = null;
  }
  renderVoices();
  controls();
}
function renderVoiceResult(data) {
  const profile = data.voice?.effective;
  $("demo-voice-result").textContent =
    !data.tts_failed && Object.hasOwn(VOICE_LABELS, profile)
      ? demoCopy().voice +
        ": " +
        voiceLabel(profile) +
        (data.voice.fallback ? " · " + demoCopy().voiceFallback : "")
      : "";
}
$("demo-voice").addEventListener("change", () => {
  if (
    !state.connected ||
    state.sessionId ||
    state.turnBusy ||
    state.previewBusy ||
    state.micStarting ||
    state.mic
  ) {
    $("demo-voice").value = state.demoVoice;
    return;
  }
  const selected = Array.from($("demo-voice").options).find(
    (option) => option.selected && !option.disabled,
  );
  if (selected) {
    stopAudio();
    state.demoVoice = selected.value;
    $("demo-voice-result").textContent = "";
  }
  renderVoices();
});
async function previewVoice() {
  if ($("demo-voice-preview").disabled) return;
  const generation = state.generation;
  state.previewBusy = true;
  stopAudio();
  controls();
  status("demo-status", demoCopy().voicePreviewLoading);
  try {
    const data = await post("/api/demo/voices/preview", {
      language: state.demoLanguage,
      voice: state.demoVoice,
    });
    if (generation !== state.generation || !state.connected) return;
    status("demo-status", demoCopy().voicePreviewReady);
    playReply(data);
    renderVoiceResult(data);
  } catch (_) {
    if (generation === state.generation)
      status("demo-status", demoCopy().voicePreviewFailed, "error");
  } finally {
    if (generation === state.generation) {
      state.previewBusy = false;
      controls();
    }
  }
}
$("demo-voice-preview").addEventListener("click", previewVoice);
async function api(path, options = {}) {
  const generation = state.generation;
  const controller = new AbortController();
  state.controllers.add(controller);
  const streaming =
    path === "/api/turn" &&
    new Headers(options.headers || {}).get("Accept") === "application/x-ndjson";
  if (streaming) state.turnController = controller;
  const timeout = setTimeout(
    () => controller.abort(),
    streaming ? 120000 : 45000,
  );
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: {
        Authorization: "Bearer " + state.credential,
        ...options.headers,
      },
    });
    if (generation !== state.generation)
      throw new DOMException("Cancelled", "AbortError");
    const data =
      response.ok &&
      streaming &&
      response.headers.get("Content-Type")?.startsWith("application/x-ndjson")
        ? await readTurnStream(response, controller)
        : await response.json();
    if (!response.ok) {
      const error = new Error(demoCopy().failed);
      error.status = response.status;
      error.code = typeof data.detail === "string" ? data.detail : data.error;
      throw error;
    }
    return data;
  } finally {
    clearTimeout(timeout);
    state.controllers.delete(controller);
    if (state.turnController === controller) state.turnController = null;
  }
}
function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
function clearReservation() {
  Object.assign(reservation, {
    sessionId: null,
    holdId: null,
    bookingId: null,
    acknowledged: false,
    busy: false,
    uncertain: false,
  });
  $("reservation-recap").hidden = true;
  $("reservation-cancel").hidden = true;
  $("reservation-recap-text").textContent = "";
}
function logout() {
  state.generation++;
  for (const controller of state.controllers) controller.abort();
  state.controllers.clear();
  stopMic();
  stopAudio();
  state.credential = "";
  state.connected = false;
  state.sessionId = state.callId = null;
  state.turnBusy = state.readBusy = state.previewBusy = false;
  state.page = 1;
  state.hasMore = false;
  state.latestBooking = null;
  state.demoVoice = "azure";
  state.voiceCatalog = null;
  clearReservation();
  for (const id of ["demo-messages", "bookings", "call-history"])
    $(id).replaceChildren();
  $("operator-token").value = $("demo-text").value = "";
  localize();
  for (const id of [
    "auth-status",
    "demo-status",
    "booking-status",
    "history-status",
    "reservation-status",
  ])
    status(id, demoCopy().signIn);
}
async function connect() {
  const credential = $("operator-token").value.trim();
  if (!credential) return;
  state.credential = credential;
  $("operator-token").value = "";
  const generation = state.generation;
  controls();
  status("auth-status", demoCopy().loading);
  try {
    await api("/api/catalogue");
    if (generation !== state.generation) return;
    state.connected = true;
    localize();
    status("auth-status", demoCopy().tokenHelp, "success");
    status("demo-status", demoCopy().ready);
    status(
      "reservation-status",
      state.bookingReady
        ? demoCopy().reservationReady
        : demoCopy().bookingMissing,
    );
    await Promise.allSettled([loadBookings(), loadHistory(), loadVoices()]);
  } catch (error) {
    if (generation === state.generation) {
      logout();
      status("auth-status", demoCopy().authFailed, "error");
    }
  } finally {
    if (generation === state.generation) controls();
  }
}
function addMessage(label, text) {
  const element = document.createElement("div");
  element.className = "message" + (label === demoCopy().you ? " user" : "");
  element.lang = state.replyLanguage;
  const heading = document.createElement("strong");
  heading.textContent = label;
  const content = document.createElement("span");
  content.textContent = String(text || "");
  element.append(heading, content);
  $("demo-messages").append(element);
  element.scrollIntoView({ block: "nearest" });
  return element;
}
function selectBooking(change) {
  if (
    !change ||
    !["confirmed", "cancelled"].includes(change.action) ||
    !/^[1-9]\d*$/.test(String(change.id)) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(change.date)
  )
    return false;
  state.latestBooking = { id: String(change.id), date: change.date };
  $("booking-date").value = change.date;
  state.page = 1;
  state.hasMore = false;
  return true;
}
function appendBookingLink(container, change) {
  if (!selectBooking(change)) return;
  const generation = state.generation;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary booking-link";
  button.textContent = `${demoCopy().viewBooking} #${change.id}`;
  button.addEventListener("click", async () => {
    if (generation !== state.generation || !state.connected) return;
    selectBooking(change);
    await loadBookings();
    if (generation !== state.generation || !state.connected) return;
    const row = Array.from($("bookings").children).find(
      (element) => element.dataset.bookingId === String(change.id),
    );
    const target = row || $("bookings-title");
    target.scrollIntoView({ block: "center" });
    target.focus({ preventScroll: true });
  });
  container.append(button);
}
function recapPlayedMessage() {
  return {
    et: "Kokkuvõte esitatud. Kinnitamiseks ütle „Jah, kinnitan.”",
    en: 'Recap delivered. To confirm, say "Yes, confirm."',
    ru: "Итог озвучен. Для подтверждения скажите «Да, подтверждаю.»",
  }[state.replyLanguage];
}
async function startDemo() {
  if (
    !requireDemoConnection() ||
    !state.voiceReady ||
    state.sessionId ||
    state.turnBusy ||
    state.previewBusy
  )
    return;
  const generation = state.generation;
  state.turnBusy = true;
  stopAudio();
  controls();
  try {
    const data = await post("/api/demo/session", {
      language: state.demoLanguage,
      voice: state.demoVoice,
    });
    if (generation !== state.generation) return;
    state.sessionId = data.session_id;
    state.callId = data.call_id;
    state.replyLanguage = data.language;
    $("demo-messages").replaceChildren();
    addMessage(demoCopy().assistant, data.greeting);
    status(
      "demo-status",
      data.tts_failed ? demoCopy().textFallback : demoCopy().ready,
    );
    stopAudio();
    playReply(data);
    renderVoiceResult(data);
  } catch (error) {
    if (generation === state.generation)
      status("demo-status", demoCopy().failed, "error");
  } finally {
    if (generation === state.generation) {
      state.turnBusy = false;
      controls();
    }
  }
}
async function sendTurn(input) {
  if (
    !state.connected ||
    !state.sessionId ||
    state.turnBusy ||
    state.micStarting
  )
    return;
  const generation = state.generation,
    receipt = currentRecap(state.recap) ? state.recapDeliveryId : null;
  state.turnBusy = true;
  stopAudio();
  controls();
  status("demo-status", demoCopy().responding);
  try {
    const data = await api("/api/turn", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson",
      },
      body: JSON.stringify({
        session_id: state.sessionId,
        ...input,
        language: state.demoLanguage,
        ...(receipt ? { recap_delivery_id: receipt } : {}),
      }),
    });
    if (generation !== state.generation) return;
    state.replyLanguage = data.language;
    const heard = addMessage(demoCopy().you, data.text_heard);
    const message =
      data._stream?.replyNode || addMessage(demoCopy().assistant, data.reply);
    if (data._stream) $("demo-messages").insertBefore(heard, message);
    $("demo-text").value = "";
    status(
      "demo-status",
      data.outcome === "unknown_outcome"
        ? demoCopy().unknown
        : data.tts_failed
          ? demoCopy().textFallback
          : demoCopy().ready,
      ["unknown_outcome", "tools_failed"].includes(data.outcome) ? "error" : "",
    );
    const recap = renderRecap(data, message, data._stream?.receivedAt);
    if (data._stream) finishStreamPlayback(data, recap);
    else playReply(data, recap);
    renderVoiceResult(data);
    const change = (data.booking_changes || []).at(-1);
    if (change) appendBookingLink(message, change);
    await Promise.allSettled([loadBookings(), loadHistory()]);
  } catch (error) {
    if (generation === state.generation) {
      status(
        "demo-status",
        demoCopy().failed + " " + demoCopy().noRetry,
        "error",
      );
      if ([404, 410].includes(error.status)) state.sessionId = null;
    }
  } finally {
    if (generation === state.generation) {
      state.turnBusy = false;
      controls();
    }
  }
}
async function endDemo() {
  if (!state.sessionId || state.turnBusy) return;
  const generation = state.generation;
  stopMic();
  stopAudio();
  state.turnBusy = true;
  controls();
  try {
    await api("/api/demo/session/" + encodeURIComponent(state.sessionId), {
      method: "DELETE",
    });
    if (generation !== state.generation) return;
    state.sessionId = null;
    $("demo-messages").replaceChildren();
    status("demo-status", demoCopy().ended);
  } catch (error) {
    if (generation === state.generation) {
      if ([404, 410].includes(error.status)) state.sessionId = null;
      status("demo-status", demoCopy().failed, "error");
    }
  } finally {
    if (generation === state.generation) {
      state.turnBusy = false;
      controls();
    }
  }
}
async function prepareReservation() {
  if (
    !state.connected ||
    !state.bookingReady ||
    reservation.busy ||
    reservation.uncertain ||
    reservation.holdId ||
    reservation.bookingId
  )
    return;
  const generation = state.generation;
  reservation.busy = true;
  reservation.holdId = null;
  reservation.acknowledged = false;
  $("reservation-recap").hidden = true;
  controls();
  status("reservation-status", demoCopy().loading);
  try {
    if (!reservation.sessionId) {
      const session = await post("/api/booking/session", {
        language: state.demoLanguage,
      });
      if (generation !== state.generation) return;
      reservation.sessionId = session.session_id;
    }
    const data = await post("/api/restaurant/reservation/prepare", {
      session_id: reservation.sessionId,
      date: $("reservation-date").value,
      start_time: $("reservation-time").value,
      party_size: Number($("reservation-party").value),
    });
    if (generation !== state.generation) return;
    if (data.restaurant_unavailable || !data.ok) {
      status(
        "reservation-status",
        demoCopy().unavailable +
          (data.alternatives?.length ? " " + data.alternatives.join(", ") : ""),
        "error",
      );
      return;
    }
    reservation.holdId = data.hold_id;
    reservation.date = data.recap.date;
    $("reservation-recap-text").textContent = data.recap_text;
    $("reservation-recap").hidden = false;
    status("reservation-status", demoCopy().recapTitle);
  } catch (error) {
    if (generation === state.generation)
      status("reservation-status", demoCopy().failed, "error");
  } finally {
    if (generation === state.generation) {
      reservation.busy = false;
      controls();
    }
  }
}
async function readReservation() {
  if (!reservation.holdId || reservation.busy) return;
  const generation = state.generation;
  reservation.busy = true;
  controls();
  try {
    await post("/api/booking/recap", {
      session_id: reservation.sessionId,
      hold_id: reservation.holdId,
    });
    if (generation !== state.generation) return;
    reservation.acknowledged = true;
    status("reservation-status", demoCopy().acknowledged);
  } catch (error) {
    if (generation === state.generation) {
      reservation.holdId = null;
      $("reservation-recap").hidden = true;
      status("reservation-status", demoCopy().failed, "error");
    }
  } finally {
    if (generation === state.generation) {
      reservation.busy = false;
      controls();
    }
  }
}
async function mutateReservation(cancel = false) {
  if (
    reservation.busy ||
    reservation.uncertain ||
    !state.connected ||
    (!cancel && !reservation.acknowledged)
  )
    return;
  const generation = state.generation;
  reservation.busy = true;
  controls();
  status("reservation-status", demoCopy().loading);
  try {
    const data = await post(
      cancel ? "/api/booking/cancel" : "/api/booking/confirm",
      {
        session_id: reservation.sessionId,
        ...(cancel
          ? { booking_id: reservation.bookingId }
          : { hold_id: reservation.holdId }),
        consent: true,
      },
    );
    if (generation !== state.generation) return;
    if (data.ok !== true || data.error) throw new Error("closed result");
    if (cancel) {
      reservation.bookingId = null;
      $("reservation-cancel").hidden = true;
    } else {
      reservation.bookingId = String(data.booking.id);
      reservation.holdId = null;
      $("reservation-recap").hidden = true;
      $("reservation-cancel").hidden = false;
    }
    status(
      "reservation-status",
      cancel ? demoCopy().cancelled : demoCopy().confirmed,
      "success",
    );
    const identifier = cancel ? data.booking_id : data.booking.id;
    appendBookingLink($("reservation-status"), {
      id: identifier,
      date: reservation.date,
      action: cancel ? "cancelled" : "confirmed",
    });
    await Promise.allSettled([loadBookings(), loadHistory()]);
  } catch (error) {
    if (generation === state.generation) {
      reservation.uncertain = true;
      status("reservation-status", demoCopy().unknown, "error");
    }
  } finally {
    if (generation === state.generation) {
      reservation.busy = false;
      controls();
    }
  }
}
async function loadBookings() {
  if (!state.connected) return;
  const generation = state.generation,
    day = $("booking-date").value,
    page = state.page,
    view = ++state.bookingView;
  state.readBusy = true;
  controls();
  status("booking-status", demoCopy().loading);
  try {
    const data = await api(
      `/api/bookings?date=${encodeURIComponent(day)}&page=${page}&length=50`,
    );
    if (
      generation !== state.generation ||
      view !== state.bookingView ||
      day !== $("booking-date").value ||
      page !== state.page
    )
      return;
    $("bookings").replaceChildren();
    for (const row of data.items) {
      const element = document.createElement("div");
      element.className = "booking-row";
      element.dataset.bookingId = String(row.id);
      element.tabIndex = -1;
      if (
        state.latestBooking?.date === day &&
        state.latestBooking.id === String(row.id)
      )
        element.classList.add("booking-recent");
      const label = document.createElement("strong");
      label.textContent = `${row.start_local.slice(11, 16)}–${row.end_local.slice(11, 16)} · ${row.provider_name}`;
      const detail = document.createElement("span");
      detail.textContent = `${row.service_id} ${demoCopy().guests} · ${row.status === "confirmed" ? demoCopy().booked : demoCopy().cancelledState} · #${row.id}`;
      element.append(label, detail);
      $("bookings").append(element);
    }
    state.hasMore = data.has_more === "unknown";
    $("booking-page").textContent = String(page);
    status(
      "booking-status",
      data.items.length ? `${data.items.length}` : demoCopy().empty,
    );
  } catch (error) {
    if (generation === state.generation && view === state.bookingView) {
      $("bookings").replaceChildren();
      status("booking-status", demoCopy().failed, "error");
    }
  } finally {
    if (generation === state.generation && view === state.bookingView) {
      state.readBusy = false;
      controls();
    }
  }
}
async function loadHistory() {
  if (!state.connected) return;
  const generation = state.generation;
  try {
    const data = await api("/api/call-history?page=1&length=10");
    if (generation !== state.generation) return;
    $("call-history").replaceChildren();
    for (const call of data.items) {
      const element = document.createElement("div");
      element.className = "booking-row";
      const label = document.createElement("strong");
      label.textContent = `${call.channel === "telephone" ? demoCopy().telephoneConversation : demoCopy().browserConversation} · ${{ et: "Eesti", en: "English", ru: "Русский" }[call.language] || ""} · ${call.turns} ${demoCopy().messages}`;
      const detail = document.createElement("span");
      detail.textContent =
        call.outcome === "in_progress"
          ? demoCopy().active
          : [
                "ok",
                "tools_ok",
                "completed",
                "booking_confirmed",
                "booking_cancelled",
                "hold_created",
              ].includes(call.outcome)
            ? demoCopy().completed
            : demoCopy().needsAttention;
      element.append(label, detail);
      $("call-history").append(element);
    }
    status(
      "history-status",
      data.items.length ? `${data.items.length}` : demoCopy().noHistory,
    );
  } catch (error) {
    if (generation === state.generation)
      status("history-status", demoCopy().failed, "error");
  }
}
function renderInformation() {
  if (!state.restaurant) return;
  const data = state.restaurant,
    language = uiLanguage();
  $("restaurant-name").textContent = data.name;
  $("menu-list").replaceChildren();
  for (const item of data.menu) {
    const element = document.createElement("li");
    element.textContent = item.name[language];
    $("menu-list").append(element);
  }
  $("allergy-notice").textContent = data.allergy_notice[language];
  $("restaurant-policies").textContent = data.policies[language];
  $("opening-hours").replaceChildren();
  [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
  ].forEach((day, index) => {
    const hours = data.opening_hours[day];
    const term = document.createElement("dt"),
      value = document.createElement("dd");
    term.textContent = DAYS[language][index];
    value.textContent = hours
      ? `${hours.start}–${hours.end}`
      : demoCopy().closed;
    $("opening-hours").append(term, value);
  });
  $("reservation-party").max = data.maximum_party_size;
  $("reservation-time").step = data.slot_interval_minutes * 60;
  $("reservation-duration").textContent =
    data.reservation_duration_minutes + " min";
  $("reservation-date").max = tallinnDay(data.advance_days);
  $("service-status").textContent = state.voiceReady
    ? demoCopy().voiceConfigured
    : demoCopy().voiceMissing;
}
async function loadPublic() {
  try {
    const [information, response] = await Promise.all([
      fetch("/api/public/restaurant"),
      fetch("/api/status"),
    ]);
    if (!information.ok || !response.ok) throw new Error("unavailable");
    const data = await information.json(),
      services = await response.json();
    state.restaurant = data.restaurant;
    state.bookingReady = data.table_booking_ready === true;
    state.voiceReady = services.capabilities.text_turn_ready === true;
    state.audioReady = services.capabilities.audio_turn_ready === true;
    renderInformation();
    controls();
    if (!state.bookingReady)
      status("reservation-status", demoCopy().bookingMissing);
  } catch (_) {
    status("information-status", demoCopy().failed, "error");
  }
}
$("auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  connect();
});
$("logout").addEventListener("click", logout);
$("demo-start").addEventListener("click", startDemo);
$("demo-end").addEventListener("click", endDemo);
$("demo-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("demo-text").value.trim();
  if (text) sendTurn({ text });
});
$("demo-mic").addEventListener("click", () => toggleMic());
$("demo-language").addEventListener("change", (event) => {
  const selected = event.target;
  if (
    !(selected instanceof HTMLInputElement) ||
    selected.name !== "demo-language" ||
    !["et", "en", "ru"].includes(selected.value)
  )
    return;
  if (
    state.sessionId ||
    state.turnBusy ||
    state.previewBusy ||
    state.micStarting ||
    state.mic ||
    reservation.busy ||
    reservation.sessionId
  ) {
    controls();
    return;
  }
  stopAudio();
  state.demoLanguage = selected.value;
  $("demo-voice-result").textContent = "";
  localize();
  status("demo-status", state.connected ? demoCopy().ready : demoCopy().signIn);
  status(
    "reservation-status",
    state.connected
      ? state.bookingReady
        ? demoCopy().reservationReady
        : demoCopy().bookingMissing
      : demoCopy().signIn,
  );
});
$("demo-recap-read").addEventListener("click", () => {
  acknowledgeRecap(state.recap);
});
for (const button of document.querySelectorAll("[data-example]"))
  button.addEventListener("click", () => {
    const examples = {
      reservation: [
        "Soovin broneerida laua.",
        "I'd like to reserve a table.",
        "Я хочу забронировать столик.",
      ],
      menu: ["Milline on menüü?", "What is on the menu?", "Что есть в меню?"],
      hours: [
        "Millal restoran avatud on?",
        "What are your opening hours?",
        "Какие у вас часы работы?",
      ],
    };
    sendTurn({
      text: examples[button.dataset.example][
        { et: 0, en: 1, ru: 2 }[uiLanguage()]
      ],
    });
  });
$("reservation-form").addEventListener("submit", (event) => {
  event.preventDefault();
  prepareReservation();
});
$("reservation-read").addEventListener("click", readReservation);
$("reservation-confirm").addEventListener("click", () => mutateReservation());
$("reservation-cancel").addEventListener("click", () =>
  mutateReservation(true),
);
$("reservation-end").addEventListener("click", async () => {
  if (!reservation.sessionId || reservation.busy || reservation.uncertain)
    return;
  const generation = state.generation;
  reservation.busy = true;
  controls();
  try {
    await api(
      "/api/demo/session/" + encodeURIComponent(reservation.sessionId),
      { method: "DELETE" },
    );
    if (generation !== state.generation) return;
    clearReservation();
    status("reservation-status", demoCopy().ended);
  } catch (error) {
    if (generation === state.generation) {
      if ([404, 410].includes(error.status)) clearReservation();
      status("reservation-status", demoCopy().failed, "error");
    }
  } finally {
    if (generation === state.generation) {
      reservation.busy = false;
      controls();
    }
  }
});
$("refresh").addEventListener("click", () =>
  Promise.allSettled([loadBookings(), loadHistory()]),
);
$("booking-date").addEventListener("change", () => {
  state.page = 1;
  loadBookings();
});
$("booking-prev").addEventListener("click", () => {
  state.page--;
  loadBookings();
});
$("booking-next").addEventListener("click", () => {
  state.page++;
  loadBookings();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopMic();
    $("demo-audio").pause();
  }
});
window.addEventListener("pagehide", () => {
  stopMic();
  stopAudio();
  for (const controller of state.controllers) controller.abort();
});
$("booking-date").value = tallinnDay();
$("reservation-date").value = tallinnDay(1);
$("reservation-date").min = tallinnDay();
$("reservation-date").max = tallinnDay(90);
localize();
loadPublic();
