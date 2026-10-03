"""Approved conversational wording; caller text never becomes a success claim."""

from __future__ import annotations

import re


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[.,!?…]", " ", text.casefold()).split())


# Match whole standalone utterances. "Thanks, book a room" must reach planning.
INTENTS = {
    "greeting": {
        "tere",
        "tervist",
        "hei",
        "hello",
        "hi",
        "hey",
        "hello there",
        "good morning",
        "good afternoon",
        "good evening",
        "tere hommikust",
        "привет",
        "здравствуйте",
        "добрый день",
        "доброе утро",
        "добрый вечер",
    },
    "thanks": {"aitäh", "suur tänu", "tänan", "thanks", "thank you", "thanks a lot", "спасибо", "большое спасибо", "спасибо большое", "благодарю"},
    "goodbye": {"head aega", "nägemist", "bye", "goodbye", "bye bye", "до свидания", "пока", "всего доброго"},
    "decline": {
        "ei",
        "ei aitäh",
        "ei ära kinnita",
        "no",
        "no thanks",
        "no thank you",
        "no don't confirm",
        "нет",
        "нет спасибо",
        "нет не подтверждайте",
        "не подтверждайте",
    },
    "repeat": {
        "korda palun",
        "palun korda",
        "korda uuesti",
        "ma ei saanud aru",
        "palun korda kuupäeva",
        "palun korda kellaaega",
        "mis kuupäev see oli",
        "repeat that",
        "please repeat that",
        "say that again",
        "could you repeat that",
        "i didn't understand",
        "what was the date",
        "please repeat the date",
        "what was the time",
        "please repeat the time",
        "повторите пожалуйста",
        "пожалуйста повторите",
        "повторите",
        "можете повторить",
        "повторите ещё раз",
        "повторите еще раз",
        "я не понял",
        "я не поняла",
        "повторите дату",
        "какая была дата",
        "повторите время",
        "какое было время",
    },
    "frustrated": {
        "see on segane",
        "see ei tööta",
        "this is confusing",
        "this isn't working",
        "непонятно",
        "это непонятно",
        "это не работает",
    },
    "identity": {
        "kes sa oled",
        "kas sa oled robot",
        "kas sa oled inimene",
        "who are you",
        "are you a robot",
        "are you human",
        "кто вы",
        "кто ты",
        "вы робот",
        "вы человек",
    },
    "how_are_you": {"kuidas sul läheb", "how are you", "how are you doing", "как дела", "как у вас дела"},
    "human": {
        "soovin inimesega rääkida",
        "kas saan inimesega rääkida",
        "can i speak to a person",
        "can i speak to a human",
        "можно поговорить с человеком",
        "хочу поговорить с человеком",
        "можно поговорить с сотрудником",
    },
}

REPLIES = {
    "et": {
        "greeting": ("Tere! Kuidas saan aidata?", "Tere! Millega saan aidata?"),
        "thanks": (
            "Hea meelega! Kas saan veel millegagi aidata?",
            "Palun! Kas sul on veel mõni küsimus?",
        ),
        "goodbye": ("Aitäh helistamast. Head päeva!", "Head aega ja kena päeva!"),
        "decline": (
            "Selge. Millega saan veel aidata?",
            "Hästi. Kas soovid midagi muud küsida?",
        ),
        "repeat": (
            "Muidugi. Millist osa soovid uuesti kuulda?",
            "Milline detail jäi ebaselgeks?",
        ),
        "frustrated": (
            "Vabandust, see jäi segaseks. Võtame ühe asja korraga. Millega soovid alustada?",
        ),
        "identity": (
            "Olen Meretuule hotelli ja spaa tehisintellekti abiline. Aitan demo küsimuste ja testbroneeringutega.",
        ),
        "how_are_you": ("Olen valmis aitama. Mida soovid teha?",),
        "human": (
            "Selles demos ei saa ma kõnet inimesele suunata. Saan aidata testbroneeringuga. Kas soovid seda proovida?",
        ),
    },
    "en": {
        "greeting": ("Hello! How can I help you?", "Hi! What can I help you with?"),
        "thanks": (
            "You're welcome! Can I help with anything else?",
            "Happy to help. Do you have any other questions?",
        ),
        "goodbye": (
            "Thanks for calling. Have a lovely day!",
            "Goodbye, and have a great day!",
        ),
        "decline": (
            "No problem. What else can I help with?",
            "Of course. Would you like help with something else?",
        ),
        "repeat": (
            "Of course. Which part would you like me to repeat?",
            "Which detail would you like to hear again?",
        ),
        "frustrated": (
            "Sorry, that wasn't clear. Let's take it one step at a time. What would you like to start with?",
        ),
        "identity": (
            "I'm Meretuule's AI assistant. I can help with questions about this demo and test bookings.",
        ),
        "how_are_you": ("I'm ready to help. What would you like to do?",),
        "human": (
            "This demo can't transfer calls to a person. I can help with a test booking. Would you like to try that?",
        ),
    },
    "ru": {
        "greeting": (
            "Здравствуйте! Чем могу помочь?",
            "Здравствуйте! Что вы хотите сделать?",
        ),
        "thanks": (
            "Пожалуйста! Могу помочь ещё чем-нибудь?",
            "Пожалуйста! Есть ещё вопросы?",
        ),
        "goodbye": (
            "Спасибо за звонок. Хорошего дня!",
            "До свидания! Всего доброго!",
        ),
        "decline": (
            "Хорошо. Чем ещё могу помочь?",
            "Понятно. Хотите спросить что-нибудь ещё?",
        ),
        "repeat": (
            "Конечно. Какую часть повторить?",
            "Какой именно момент нужно повторить?",
        ),
        "frustrated": (
            "Извините, получилось непонятно. Давайте по одному вопросу. С чего хотите начать?",
        ),
        "identity": (
            "Я помощник на основе искусственного интеллекта в демонстрации Meretuule. Могу помочь с вопросами и тестовыми бронированиями.",
        ),
        "how_are_you": ("Могу помочь. Что вы хотите сделать?",),
        "human": (
            "В этой демонстрации я не могу перевести звонок сотруднику. Могу помочь с тестовым бронированием. Хотите попробовать?",
        ),
    },
}

# Alternatives are reviewed questions, not a permit to improvise booking facts.
QUESTIONS = {
    "et": {
        "booking_kind": ("Kas soovid spaahooldust või hotellituba?",),
        "spa_service": (
            "Millist spaahooldust soovid?",
            "Milline hooldus sulle huvi pakub?",
        ),
        "date": ("Mis kuupäev sulle sobiks?", "Milliseks päevaks soovid aega?"),
        "time": ("Mis kell sulle sobiks?", "Millist kellaaega eelistad?"),
        "arrival": ("Millal soovid saabuda?",),
        "departure": ("Millal soovid lahkuda?",),
        "adults": ("Mitu täiskasvanut tuleb?",),
        "children": ("Kas kaasa tuleb ka lapsi? Kui jah, siis mitu?",),
        "room": ("Millist toatüüpi eelistad?",),
        "guest": ("Millist demo külalist soovid kasutada?",),
    },
    "en": {
        "booking_kind": ("Would you like a spa appointment or a hotel room?",),
        "spa_service": (
            "Which spa treatment would you like?",
            "Which treatment interests you?",
        ),
        "date": ("What date works for you?", "Which day would you prefer?"),
        "time": ("What time works for you?", "What time would you prefer?"),
        "arrival": ("When would you like to arrive?",),
        "departure": ("When would you like to leave?",),
        "adults": ("How many adults are coming?",),
        "children": ("Are any children coming? If so, how many?",),
        "room": ("Which room type would you prefer?",),
        "guest": ("Which demo guest would you like to use?",),
    },
    "ru": {
        "booking_kind": ("Вы хотите забронировать спа-процедуру или номер в отеле?",),
        "spa_service": (
            "Какую спа-процедуру хотите забронировать?",
            "Какая процедура вас интересует?",
        ),
        "date": ("Какая дата вам подходит?", "На какой день хотите записаться?"),
        "time": ("Какое время вам подходит?", "Какое время вам удобнее?"),
        "arrival": ("Когда хотите заехать?",),
        "departure": ("Когда хотите выехать?",),
        "adults": ("Сколько взрослых будет всего?",),
        "children": ("Сколько детей будет с вами?",),
        "room": ("Какой тип номера вы предпочитаете?",),
        "guest": ("Какого тестового гостя хотите выбрать?",),
    },
}

STYLE_INSTRUCTIONS = {
    "et": "Räägi sõbraliku abilisena, lühikeste kõnelausete ja ühe küsimusega korraga. Vali puuduvate andmete küsimus natural_questions valikutest. Ära küsi uuesti juba antud detaili. Ära korda tervitust ega demo tutvustust igas voorus. Väldi bürokraatlikku sõnastust, loetelude ettelugemist, täitesõnu ja väljamõeldud naeru. Ära väida, et oled inimene. Vastused ja küsimused ei tohi lubada kinnitamata broneeringut, hinda, saadavust ega inimesele suunamist. Serveri kokkuvõte ja nõusoleku sõnad jäävad täpseks. Vali kõigepealt üks täpsustav küsimus; ära loe korraga kõiki puuduvate andmete küsimusi ette.",
    "en": "Speak like a friendly assistant, with short spoken sentences and one question at a time. Choose missing-detail questions from natural_questions. Keep details the caller already supplied. Do not restart the greeting or repeat the demo disclosure every turn. Avoid bureaucratic wording, long lists, filler noises and invented laughter. Do not pretend to be human. Never add an unverified booking, price, availability or transfer claim. The server's recap and consent wording stay exact. Pick one clarification question; do not read out the whole list of missing details.",
    "ru": "Говори как дружелюбный помощник: короткими фразами и по одному вопросу за раз. Выбирай вопросы о недостающих данных из natural_questions. Сохраняй сведения, которые собеседник уже сообщил. Не начинай каждый ответ с приветствия и не повторяй описание демонстрации в каждом ходе. Избегай канцелярских оборотов, длинных списков, слов-паразитов и выдуманного смеха. Не выдавай себя за человека. Не обещай неподтверждённое бронирование, цену, наличие мест или перевод звонка сотруднику. Серверный текст итогов бронирования и слова согласия должны оставаться точными. Задавай один уточняющий вопрос, а не весь список вопросов о недостающих данных.",
}


def intent_for(text: str) -> str | None:
    value = normalize(text)
    return next(
        (intent for intent, phrases in INTENTS.items() if value in phrases), None
    )


def spa_hours_focus(text: object) -> bool:
    """Recognize a bounded spa schedule question without authorizing a booking."""
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return False
    value = normalize(text)
    if re.search(
        r"\b(?:broneer\w*|brooneer\w*|bruneer\w*|kinnita\w*|tühist\w*|book\w*|reserv\w*|"
        r"confirm\w*|cancel\w*|hotell\w*|hotel\w*|toa\w*|tuba\w*|tube\w*|"
        r"room\w*|stay\w*|majut\w*)\b", value,
    ):
        return False
    if not re.search(
        r"\b(?:spaa?\w*|teenindaja\w*|teenusepakkuja\w*|terapeut\w*|"
        r"massöör\w*|therapist\w*|provider\w*)\b", value,
    ):
        return False
    if not re.search(
        r"\b(?:mis|millal|kas|palun|näita|ütle|kontrolli|what|when|can|could|"
        r"please|show|tell|check)\b", value,
    ):
        return False
    if re.search(
        r"\b(?:tööa\w*|tööplaan\w*|töögraafik\w*|graafik\w*|teenindusa\w*|"
        r"lõunapaus\w*|puhkepaus\w*|paus\w*|opening hours|working hours|"
        r"work plan|schedule\w*|timetable\w*|break\w*|lunch)\b", value,
    ):
        return True
    return bool(
        re.search(r"\b(?:kell|millal|when|what time|hours)\b", value)
        and re.search(
            r"\b(?:tööt\w*|alustab|lõpetab|avatud|lahti|work\w*|start\w*|"
            r"finish\w*|open\w*|close\w*)\b", value,
        )
    )


def read_focus(text: str) -> str | None:
    value = normalize(text)
    if spa_hours_focus(text):
        return "hours"
    if re.search(r"\b(?:tööa\w*|avatud|lahti|opening hours|working hours|часы работы|время работы|график работы|режим работы|время открытия|время закрытия)\b", value):
        return "hours"
    if re.search(
        r"\b(?:spa\w*|spaa\w*|hooldus\w*|teenus\w*|treatment\w*|service\w*|спа\w*|процедур\w*|услуг\w*|массаж\w*)\b", value
    ):
        return "services"
    return None


def approved_dialogue(language: str) -> set[str]:
    return {
        text
        for group in (REPLIES[language], QUESTIONS[language])
        for variants in group.values()
        for text in variants
    }


class Conversation:
    """Only bounded intent/counters survive a turn; never the caller's words."""

    def __init__(self) -> None:
        self.intent: str | None = None
        self.reply: str | None = None
        self.focus: str | None = None
        self._counts: dict[tuple[str, str], int] = {}

    def observe(self, text: str, language: str) -> None:
        self.intent = intent_for(text)
        self.focus = read_focus(text)
        self.reply = None
        if self.intent is not None:
            choices = REPLIES[language][self.intent]
            key = (language, self.intent)
            count = self._counts.get(key, 0)
            self.reply = choices[count % len(choices)]
            self._counts[key] = count + 1
