"""Case-tolerant date/count parsing with fixed Tallinn calendar expectations."""

import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.restaurant_call import parse_restaurant_request
from app.restaurant_dates import resolve_restaurant_date

NOW = datetime(2026, 10, 3, 12, tzinfo=ZoneInfo("Europe/Tallinn"))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("homme", "2026-10-04"),
        ("homseks", "2026-10-04"),
        ("homsele", "2026-10-04"),
        ("homsel", "2026-10-04"),
        ("homse", "2026-10-04"),
        ("hommele", "2026-10-04"),
        ("hommeks", "2026-10-04"),
        ("ülehomme", "2026-10-05"),
        ("ülehomseks", "2026-10-05"),
        ("ülehomsele", "2026-10-05"),
        ("täna", "2026-10-03"),
        ("tänaseks", "2026-10-03"),
        ("tänasele", "2026-10-03"),
        ("esmaspäevaks", "2026-10-05"),
        ("esmaspäevale", "2026-10-05"),
        ("teisipäeval", "2026-10-06"),
        ("kolmapäevaks", "2026-10-07"),
        ("neljapäevale", "2026-10-08"),
        ("reedeks", "2026-10-09"),
        ("reedele", "2026-10-09"),
        ("laupäevaks", "2026-10-10"),
        ("pühapäeval", "2026-10-04"),
        ("tomorrow", "2026-10-04"),
        ("day after tomorrow", "2026-10-05"),
        ("Monday", "2026-10-05"),
        ("завтра", "2026-10-04"),
        ("послезавтра", "2026-10-05"),
        ("понедельник", "2026-10-05"),
    ],
)
def test_relative_and_weekday_case_forms(text, expected):
    resolved = resolve_restaurant_date(text, NOW)
    assert resolved.value == expected and resolved.issue is None


@pytest.mark.parametrize(
    "text",
    [
        "neljas oktoober",
        "neljanda oktoobri",
        "neljandal oktoobril",
        "neljandaks oktoobriks",
        "neljandale oktoobrile",
        "nelja oktoobril",
        "neljale oktoobrile",
        "neljas oktoobriks",
        "neljandaks oktoober",
        "neljas oktooberile",
        "oktoobri neljas",
        "oktoobril neljandal",
        "4 oktoober",
        "4. oktoobril",
        "4.oktoober",
        "NELJAS OKTOOBER!",
        "neljas oktoober 2026",
        "4.10.2026",
        "2026-10-04",
    ],
)
def test_spoken_and_written_date_forms_share_one_calendar_date(text):
    result = parse_restaurant_request("laud " + text + " kell 14.00 kahele", now=NOW)
    assert result == {"date": "2026-10-04", "start_time": "14:00", "party_size": 2}


DAY_WORDS = (
    "esimene",
    "teine",
    "kolmas",
    "neljas",
    "viies",
    "kuues",
    "seitsmes",
    "kaheksas",
    "üheksas",
    "kümnes",
    "üheteistkümnes",
    "kaheteistkümnes",
    "kolmeteistkümnes",
    "neljateistkümnes",
    "viieteistkümnes",
    "kuueteistkümnes",
    "seitsmeteistkümnes",
    "kaheksateistkümnes",
    "üheksateistkümnes",
    "kahekümnes",
    "kahekümne esimene",
    "kahekümne teine",
    "kahekümne kolmas",
    "kahekümne neljas",
    "kahekümne viies",
    "kahekümne kuues",
    "kahekümne seitsmes",
    "kahekümne kaheksas",
    "kahekümne üheksas",
    "kolmekümnes",
    "kolmekümne esimene",
)


@pytest.mark.parametrize("day,word", list(enumerate(DAY_WORDS, 1)))
def test_all_calendar_days_spoken_as_ordinals(day, word):
    result = resolve_restaurant_date(word + " detsember", NOW)
    assert result.value == f"2026-12-{day:02d}"
    assert result.issue is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("kahekümne esimeseks oktoobriks", "2026-10-21"),
        ("kakskümmend üks oktoober", "2026-10-21"),
        ("kahekümneesimene oktoober", "2026-10-21"),
        ("kahekümne-esimene oktoober", "2026-10-21"),
        ("kahekümne   esimene oktoober", "2026-10-21"),
        ("kahekümne neljandal novembril", "2026-11-24"),
        ("kolmekümne esimesel oktoobril", "2026-10-31"),
        ("üheteistkümnendaks oktoobriks", "2026-10-11"),
        ("kaheteistkümnendal oktoobril", "2026-10-12"),
        ("neljas jaanuar", "2027-01-04"),
        ("neljas veebruar 2027", "2027-02-04"),
        ("neljas märts 2027", "2027-03-04"),
        ("neljas aprill 2027", "2027-04-04"),
        ("neljas mai 2027", "2027-05-04"),
        ("neljas juuni 2027", "2027-06-04"),
        ("neljas juuli 2027", "2027-07-04"),
        ("neljas august 2027", "2027-08-04"),
        ("neljas september 2027", "2027-09-04"),
        ("neljas oktoober 2027", "2027-10-04"),
        ("2027. aasta neljas oktoober", "2027-10-04"),
        ("neljas november", "2026-11-04"),
        ("neljas detsember", "2026-12-04"),
        ("kahekümne üheksas veebruar 2028", "2028-02-29"),
    ],
)
def test_compound_numbers_months_explicit_years_and_rollover(text, expected):
    result = resolve_restaurant_date(text, NOW)
    assert result.value == expected and result.issue is None


@pytest.mark.parametrize(
    "text,issue",
    [
        ("31. veebruar 2026", "date_invalid"),
        ("kolmekümne teine oktoober", "date_invalid"),
        ("neljakümne teine oktoober", "date_invalid"),
        ("null oktoober", "date_invalid"),
        ("29. veebruar 2026", "date_invalid"),
        ("2026-13-04", "date_invalid"),
        ("31.04.2026", "date_invalid"),
        ("homseks või ülehomseks", "date_ambiguous"),
        ("neljas või viies oktoober", "date_ambiguous"),
        ("4. kuni 5. oktoober", "date_ambiguous"),
        ("4.-5. oktoober", "date_ambiguous"),
        ("neljakümne-teine oktoober", "date_invalid"),
        ("2027 aasta neljas oktoober 2026", "date_ambiguous"),
        ("4. oktoober või 5. november", "date_ambiguous"),
        ("homseks, 5. oktoobril", "date_ambiguous"),
        ("mitte homseks", "date_ambiguous"),
        ("ei soovi homseks", "date_ambiguous"),
        ("neljas oktoober 26", "date_ambiguous"),
        ("oktoobriks", "date_incomplete"),
    ],
)
def test_invalid_or_ambiguous_date_never_reuses_a_previous_date(text, issue):
    previous = {"date": "2026-10-06", "start_time": "14:00", "party_size": 2}
    result = parse_restaurant_request(text, previous, now=NOW)
    assert "date" not in result
    assert result["date_issue"] == issue
    assert result["start_time"] == "14:00" and result["party_size"] == 2
    assert previous["date"] == "2026-10-06"


def test_date_corrections_replace_previous_date_and_clear_clarification():
    previous = {"date": "2026-10-06", "start_time": "14:00", "party_size": 2}
    assert (
        parse_restaurant_request("homseks", previous, now=NOW)["date"] == "2026-10-04"
    )
    assert (
        parse_restaurant_request("esmaspäevaks", previous, now=NOW)["date"]
        == "2026-10-05"
    )
    invalid = parse_restaurant_request("31 veebruar", previous, now=NOW)
    repaired = parse_restaurant_request("neljas oktoober", invalid, now=NOW)
    assert repaired == {"date": "2026-10-04", "start_time": "14:00", "party_size": 2}


@pytest.mark.parametrize(
    "date_text",
    ["neljale oktoobrile", "kahele novembrile", "4.10.2026", "nelja oktoobril"],
)
def test_date_words_do_not_become_guest_counts_or_clock_times(date_text):
    result = parse_restaurant_request("soovin lauda " + date_text, now=NOW)
    assert (
        "date" in result and "party_size" not in result and "start_time" not in result
    )


@pytest.mark.parametrize(
    "quantity",
    [
        "neli inimest",
        "nelja inimesega",
        "neljale inimesele",
        "neljaks külaliseks",
        "nelja külalisega",
        "neljale külalisele",
    ],
)
def test_guest_count_case_forms_remain_separate_from_dates(quantity):
    result = parse_restaurant_request(
        "soovin lauda homseks kell 14.00 " + quantity, now=NOW
    )
    assert result == {"date": "2026-10-04", "start_time": "14:00", "party_size": 4}


def test_component_counts_in_genitive_and_comitative_include_children():
    result = parse_restaurant_request(
        "laud homseks kell 14 kahe täiskasvanu ja kahe lapsega", now=NOW
    )
    assert result["party_size"] == 4


def test_relative_and_named_date_can_agree_without_becoming_ambiguous():
    assert (
        resolve_restaurant_date("homseks, neljandal oktoobril", NOW).value
        == "2026-10-04"
    )


def test_combining_characters_and_unrelated_words():
    text = unicodedata.normalize("NFD", "ülehomseks")
    assert resolve_restaurant_date(text, NOW).value == "2026-10-05"
    for text in ("hommikusöök", "homsaurus", "neljakümnene", "oktoobrilill"):
        result = resolve_restaurant_date(text, NOW)
        assert result.value is None and result.issue is None


@pytest.mark.parametrize(
    "text",
    [
        "Kas homseks olete avatud?",
        "Kas neljandal oktoobril on köök avatud?",
        "Aga homsele?",
    ],
)
def test_schedule_questions_use_the_same_date_vocabulary(text):
    from app.restaurant_answers import RestaurantQuestion, match_question

    question = match_question(text, previous=RestaurantQuestion(("hours",)), now=NOW)
    assert question.date == "2026-10-04" and question.days == (6,)
    assert question.date_issue is None


@pytest.mark.parametrize(
    "text,issue",
    [
        ("Kas 31 veebruar olete avatud?", "date_invalid"),
        ("Mis kell homseks või ülehomseks köök avatud on?", "date_ambiguous"),
    ],
)
def test_schedule_questions_do_not_hide_bad_dates_in_a_weekly_schedule(text, issue):
    from app.restaurant_answers import match_question

    question = match_question(text, now=NOW)
    assert question.date is None and question.date_issue == issue


def test_guest_count_is_not_a_human_handoff_but_a_handoff_request_still_is():
    from app.restaurant_answers import match_question

    assert match_question("Soovin lauaks homseks nelja inimesega", now=NOW) is None
    assert match_question("Palun ühenda mind inimesega", now=NOW).topics == ("staff",)
