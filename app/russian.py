"""Caller language and approved Russian speech; backend values stay unchanged."""

from __future__ import annotations

import re


def detect_language(text: str, default: str = "et") -> str:
    """Detect Russian/Estonian from final speech, retaining ambiguous turn language."""
    default = default if default in {"et", "en", "ru"} else "et"
    if not isinstance(text, str):
        return default
    if len(re.findall(r"[а-яё]", text, re.I)) >= 2:
        return "ru"
    if re.search(
        r"[õäöü]|\b(?:tere|jah|ei|kinnitan|palun|soovin|sooviks|tahaks|aitäh|"
        r"tänan|tühista|broneering|broneerida|hotelli|tuba|mis|kas|kuidas|kus|"
        r"millal|millist|kaua|kestab|maksab)\b",
        text,
        re.I,
    ):
        return "et"
    return default


RUSSIAN = {
    "Mis kuupäev sulle sobiks?": "Какая дата вам подходит?",
    "Mis kell sulle sobiks?": "Какое время вам подходит?",
    "Tere! Olen Meretuule hotelli ja spaa tehisintellekti abiline. Siin teeme ainult testbroneeringuid. Kuidas saan aidata?": "Здравствуйте! Я ИИ-помощник отеля и спа Meretuule. Здесь мы делаем только тестовые бронирования. Чем могу помочь?",
    "Palun räägi eesti või inglise keeles. Kumba keelt eelistad?": "Пожалуйста, говорите по-русски, по-эстонски или по-английски. Какой язык вы предпочитаете?",
    "{schedule}. Vaba aeg tuleb eraldi kontrollida.": "{schedule}. Доступное время нужно проверить отдельно.",
    "Palun ütle soovitud kuupäev ja kellaaeg.": "Назовите желаемую дату и время.",
    "Soovitud aeg ei ole saadaval. Palun vali teine kuupäev või kellaaeg.": "Выбранное время недоступно. Выберите другую дату или время.",
    "See kuupäev ja kellaaeg on juba möödunud. Palun vali tulevane aeg.": "Эти дата и время уже прошли. Выберите дату и время в будущем.",
    "Testbroneering ei ole kinnitatud. Enne kinnitamist tuleb uus kokkuvõte ette lugeda. Palun ütle soovitud kuupäev ja kellaaeg.": "Тестовое бронирование не подтверждено. Перед подтверждением нужно прочитать новые детали бронирования. Назовите желаемую дату и время.",
    "Tere! Olen tehisintellektil põhinev spaabroneerimise demoabiline. Broneeringud on ainult testimiseks. Kuidas saan aidata?": "Здравствуйте! Я демонстрационный помощник на основе искусственного интеллекта для бронирования спа. Бронирования только тестовые. Чем могу помочь?",
    "Tere!": "Здравствуйте!",
    "Tere! Kuidas saan aidata?": "Здравствуйте! Чем могу помочь?",
    "Tere.": "Здравствуйте.",
    "Tere": "Здравствуйте",
    "Vabandust, teenus ei ole praegu saadaval. Palun proovige hiljem uuesti.": "Извините, сервис сейчас недоступен. Попробуйте позже.",
    "Mis kuupäevaks ja kellaajaks soovid testbroneeringut?": "На какую дату и время вы хотите сделать тестовое бронирование?",
    "Mis kuupäevaks soovid testbroneeringut?": "На какую дату вы хотите сделать тестовое бронирование?",
    "Mis kellaajaks soovid testbroneeringut?": "На какое время вы хотите сделать тестовое бронирование?",
    "Edu ei ole kinnitatud. Kontrolli testbroneeringu tulemust taustsüsteemist.": "Успех операции не подтверждён. Проверьте результат тестового бронирования в системе.",
    "Toimingu tulemus on ebaselge. Edu ei ole kinnitatud. Ära korda toimingut; kontrolli taustsüsteemi.": "Результат операции неизвестен. Успех не подтверждён. Не повторяйте операцию; проверьте результат в системе.",
    "Testbroneering on kinnitatud.": "Тестовое бронирование подтверждено.",
    "Testbroneering on tühistatud.": "Тестовое бронирование отменено.",
    "See testbroneering on juba kinnitatud. Uut broneeringut ei loodud.": "Это тестовое бронирование уже подтверждено. Новое бронирование не создавалось.",
    "See testbroneering on juba tühistatud.": "Это тестовое бронирование уже отменено.",
    " Muu päring ebaõnnestus.": " Другой запрос завершился ошибкой.",
    "Vabandust, ma ei kuulnud. Palun korrake?": "Извините, не расслышала. Повторите, пожалуйста.",
    "Ma ei saa praegu hinda kinnitada.": "Сейчас я не могу подтвердить цену.",
    "Toiming ei õnnestunud; edu ei ole kinnitatud.": "Операция не выполнена; успех не подтверждён.",
    "Toiming ei õnnestunud; edu ei ole kinnitatud. Palun kontrolli testbroneeringu ettevalmistust või proovi hiljem uuesti.": "Операция не выполнена; успех не подтверждён. Проверьте подготовку тестового бронирования или попробуйте позже.",
    "Kas soovid broneerida spaahooldust või hotellituba?": "Вы хотите забронировать спа-процедуру или номер в отеле?",
    "Millist spaateenust soovid ja mis kuupäevaks?": "Какую спа-услугу и на какую дату вы хотите забронировать?",
    "Mis kellaaega eelistad?": "Какое время вам подходит?",
    "Mis kuupäevadel soovid peatuda ja mitmele külalisele?": "На какие даты и для скольких гостей нужен номер?",
    "Millist toatüüpi eelistad?": "Какой тип номера вы предпочитаете?",
    "Kas soovid veel midagi küsida?": "Хотите спросить что-нибудь ещё?",
    "Aitäh! Head päeva!": "Спасибо! Хорошего дня!",
    "Jah, kinnitan.": "Да, подтверждаю.",
    "Fiktiivne majutuse testbroneering: {room_name}, saabumine {checkin}, lahkumine {checkout}, {nights} ööd, {adults} täiskasvanut ja {children} last, külaline {guest_name}. Näidishind kokku {quoted_total} {currency}. Makseid ei koguta. Kas kinnitad selle testbroneeringu? Ütle: „{consent}”": "Тестовое бронирование в вымышленном отеле: {room_name}, заезд {checkin}, выезд {checkout}, ночей: {nights}, взрослых: {adults}, детей: {children}, гость {guest_name}. Общая демонстрационная цена: {quoted_total} {currency}. Оплата не взимается. Подтверждаете это тестовое бронирование? Скажите: «{consent}»",
    "Fiktiivne testbroneering: {service_name}, {provider_name}, {start}, ajavöönd {timezone}, külaline {guest_name}. Kas kinnitad selle testbroneeringu? Ütle: „{consent}”": "Тестовое бронирование: {service_name}, специалист {provider_name}, {start}, часовой пояс {timezone}, гость {guest_name}. Подтверждаете это тестовое бронирование? Скажите: «{consent}»",
    "{name}, kuni {capacity} külalist": "{name}, до {capacity} гостей",
    "Fiktiivse hotelli toatüübid: {choices}. Saabumine alates {checkin_time}, lahkumine kuni {checkout_time}. Mis kuupäevadel soovid peatuda ja mitmele külalisele?": "Типы номеров в вымышленном отеле: {choices}. Заезд с {checkin_time}, выезд до {checkout_time}. На какие даты и для скольких гостей нужен номер?",
    "{name}, {duration} minutit": "{name}, {duration} минут",
    "esmaspäev": "понедельник",
    "teisipäev": "вторник",
    "kolmapäev": "среда",
    "neljapäev": "четверг",
    "reede": "пятница",
    "laupäev": "суббота",
    "pühapäev": "воскресенье",
    "suletud": "закрыто",
    ", paus ": ", перерыв ",
    "{name} tööajad: {schedule}": "Время работы специалиста {name}: {schedule}",
    "Tööaegu ei ole andmebaasist kinnitatud": "Время работы не подтверждено данными системы",
    "Demo spaateenused: {choices}. Millist spaahooldust soovid?": "Демонстрационные спа-услуги: {choices}. Какую спа-процедуру вы хотите?",
    "Demo spaateenused: {choices}. {schedule}. Vaba aeg tuleb eraldi kontrollida.": "Демонстрационные спа-услуги: {choices}. {schedule}. Доступное время нужно проверить отдельно.",
    "Soovitud kuupäevadel ja külaliste arvuga vabu demotube ei ole. Kas soovid teisi kuupäevi?": "На выбранные даты для указанного числа гостей нет свободных демонстрационных номеров. Хотите выбрать другие даты?",
    "Saadaval demotoapakkumised: ": "Доступные предложения демонстрационных номеров: ",
    "{label}, {checkin} kuni {checkout}, kokku {quoted_total} {currency}": "{label}, с {checkin} по {checkout}, всего {quoted_total} {currency}",
    ". Need on fiktiivsed näidishinnad. Millist toatüüpi eelistad?": ". Это вымышленные демонстрационные цены. Какой тип номера вы предпочитаете?",
    "Selleks kuupäevaks vabu spaademo aegu ei ole. Kas soovid teist kuupäeva?": "На эту дату нет свободного времени в спа-демо. Хотите выбрать другую дату?",
    "Saadaval spaademo ajad {date}: ": "Доступное время в спа-демо на {date}: ",
    ". Mis kellaaega eelistad?": ". Какое время вам подходит?",
}


def localize(text: str, language: str) -> str:
    """Translate approved text/templates only, never arbitrary provider data."""
    return RUSSIAN.get(text, text) if language == "ru" else text
