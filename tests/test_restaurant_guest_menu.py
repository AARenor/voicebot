"""Restaurant catalogue speech never turns fictional examples into dietary advice."""

from copy import deepcopy

import pytest

from app.telephone import CallTools


@pytest.fixture
def catalogue():
    return {
        "synthetic": True,
        "source": "demo_table",
        "venue": {"name": "Meretuule restoran", "timezone": "Europe/Tallinn"},
        "tables": [],
        "rules": {},
        "menu": [
            {
                "name_et": "Roheline salat",
                "description_et": "Fiktiivne eelroa näidis, mitte päris toidu tellimine.",
                "name_en": "Green salad",
                "description_en": "A fictional starter example, not a real food order.",
                "name_ru": "Зелёный салат",
                "description_ru": "Вымышленный пример закуски, не настоящий заказ еды.",
            },
            {
                "name_et": "Ahjuköögiviljad",
                "description_et": "Fiktiivne pearoa näidis. Koostist ega allergeeniohutust ei kinnitata.",
                "name_en": "Roasted vegetables",
                "description_en": "A fictional main-course example. Ingredients and allergen safety are not verified.",
                "name_ru": "Запечённые овощи",
                "description_ru": "Вымышленный пример основного блюда. Состав и безопасность при аллергии не подтверждены.",
            },
            {
                "name_et": "Marjamagustoit",
                "description_et": "Fiktiivne magustoidu näidis. Selle demo kaudu ei võeta vastu tellimusi ega makseid.",
                "name_en": "Berry dessert",
                "description_en": "A fictional dessert example. This demo accepts no food orders or payments.",
                "name_ru": "Ягодный десерт",
                "description_ru": "Вымышленный пример десерта. Эта демонстрация не принимает заказы еды или оплату.",
            },
        ],
    }


LANGUAGE_CASES = [
    (
        "et",
        "Fiktiivsed menüünäited",
        (
            "Roheline salat: Fiktiivne eelroa näidis, mitte päris toidu tellimine.",
            "Ahjuköögiviljad: Fiktiivne pearoa näidis. Koostist ega allergeeniohutust ei kinnitata.",
            "Marjamagustoit: Fiktiivne magustoidu näidis. Selle demo kaudu ei võeta vastu tellimusi ega makseid.",
        ),
        (
            "Koostisosad",
            "allergeenid",
            "ristsaastumise",
            "sobivus eridieedile",
            "ei ole kinnitatud",
        ),
    ),
    (
        "en",
        "Fictional menu examples",
        (
            "Green salad: A fictional starter example, not a real food order.",
            "Roasted vegetables: A fictional main-course example. Ingredients and allergen safety are not verified.",
            "Berry dessert: A fictional dessert example. This demo accepts no food orders or payments.",
        ),
        (
            "Ingredients",
            "allergens",
            "cross-contact",
            "dietary suitability",
            "not verified",
        ),
    ),
    (
        "ru",
        "Вымышленные примеры меню",
        (
            "Зелёный салат: Вымышленный пример закуски, не настоящий заказ еды.",
            "Запечённые овощи: Вымышленный пример основного блюда. Состав и безопасность при аллергии не подтверждены.",
            "Ягодный десерт: Вымышленный пример десерта. Эта демонстрация не принимает заказы еды или оплату.",
        ),
        (
            "Состав",
            "аллергены",
            "перекрёстном контакте",
            "специальной диеты",
            "не подтверждены",
        ),
    ),
]


@pytest.mark.parametrize(
    "language,fictional,examples,warning", LANGUAGE_CASES, ids=["et", "en", "ru"]
)
def test_menu_does_not_replace_localized_examples_with_table_or_invented_facts(
    catalogue, language, fictional, examples, warning
):
    catalogue["tables"] = [{"label": "TABLE-METADATA-MUST-NOT-BE-SPOKEN"}]
    catalogue["menu"][0].update(
        price="999 EUR", available=True, transfer="TRANSFER-CLAIM-MUST-NOT-BE-SPOKEN"
    )
    original = deepcopy(catalogue)

    reply = CallTools._render_read_result(catalogue, language, focus="menu")

    assert isinstance(reply, str), "Valid menu examples need canonical speech"
    assert fictional in reply
    for example in examples:
        assert example in reply
    for fragment in warning:
        assert fragment in reply
    assert "TABLE-METADATA-MUST-NOT-BE-SPOKEN" not in reply
    assert "TRANSFER-CLAIM-MUST-NOT-BE-SPOKEN" not in reply
    assert "999" not in reply
    for other_language, _, other_examples, _ in LANGUAGE_CASES:
        if other_language != language:
            for example in other_examples:
                assert example not in reply
    assert catalogue == original


@pytest.mark.parametrize(
    "language,fictional,examples,warning", LANGUAGE_CASES, ids=["et", "en", "ru"]
)
def test_dietary_cannot_certify_salad_from_dish_names_or_untrusted_metadata(
    catalogue, language, fictional, examples, warning
):
    catalogue["menu"][0].update(
        {
            "name_" + language: "VEGAN-GLUTEN-FREE-SALAD-CLAIM",
            "description_" + language: "GUARANTEED-ALLERGEN-SAFE-DESCRIPTION",
            "vegan": True,
            "gluten_free": True,
            "allergens": [],
            "ingredients": ["CERTIFIED-SAFE-INGREDIENT-CLAIM"],
            "cross_contact_safe": True,
        }
    )
    catalogue["rules"] = {"dietary_verified": True, "answer": "CERTIFIED-SUITABLE"}
    original = deepcopy(catalogue)

    reply = CallTools._render_read_result(catalogue, language, focus="dietary")

    assert isinstance(reply, str), "Dietary focus needs an explicit safety caution"
    for fragment in warning:
        assert fragment in reply
    for claim in (
        "VEGAN-GLUTEN-FREE-SALAD-CLAIM",
        "GUARANTEED-ALLERGEN-SAFE-DESCRIPTION",
        "CERTIFIED-SAFE-INGREDIENT-CLAIM",
        "CERTIFIED-SUITABLE",
    ):
        assert claim not in reply
    for inferred_claim in (
        "vegan",
        "gluten",
        "gluteen",
        "веган",
        "безглютен",
        "sobib",
        "suitable",
        "подходит",
    ):
        assert inferred_claim not in reply.casefold()
    for example in examples:
        assert example not in reply
    assert fictional not in reply
    assert catalogue == original


@pytest.mark.parametrize(
    "language,fictional,examples,warning", LANGUAGE_CASES, ids=["et", "en", "ru"]
)
def test_menu_cannot_read_past_three_fixture_examples(
    catalogue, language, fictional, examples, warning
):
    catalogue["menu"].extend(
        [
            {
                "name_" + language: "FOURTH-DISH-MUST-NOT-BE-SPOKEN",
                "description_" + language: "A fourth fictional example.",
            },
            None,
            {"name_" + language: "OVERSIZED-TAIL" * 1000},
        ]
    )
    original = deepcopy(catalogue)

    reply = CallTools._render_read_result(catalogue, language, focus="menu")

    assert isinstance(reply, str)
    for example in examples:
        assert example in reply
    assert "FOURTH-DISH-MUST-NOT-BE-SPOKEN" not in reply
    assert "OVERSIZED-TAIL" not in reply
    for fragment in warning:
        assert fragment in reply
    assert len(reply) < 1600
    assert catalogue == original


@pytest.mark.parametrize("focus", ["menu", "dietary"])
def test_missing_menu_does_not_invent_dishes_or_claim_dietary_evidence(
    catalogue, focus
):
    del catalogue["menu"]
    original = deepcopy(catalogue)

    assert CallTools._render_read_result(catalogue, "en", focus=focus) is None
    assert catalogue == original


@pytest.mark.parametrize("focus", ["menu", "dietary"])
@pytest.mark.parametrize(
    "menu",
    [
        pytest.param(None, id="null-menu"),
        pytest.param({}, id="mapping-not-list"),
        pytest.param("Green salad", id="text-not-list"),
        pytest.param(42, id="number-not-list"),
        pytest.param([], id="empty-list"),
        pytest.param([None], id="null-item"),
        pytest.param([42], id="numeric-item"),
        pytest.param(["Green salad"], id="text-item"),
        pytest.param([[]], id="list-item"),
        pytest.param([{}], id="empty-item"),
        pytest.param([{"name_en": "Green salad"}], id="missing-description"),
        pytest.param([{"description_en": "A fictional example."}], id="missing-name"),
        pytest.param(
            [{"name_en": "", "description_en": "A fictional example."}], id="empty-name"
        ),
        pytest.param(
            [{"name_en": " \n ", "description_en": "A fictional example."}],
            id="blank-name",
        ),
        pytest.param(
            [{"name_en": None, "description_en": "A fictional example."}],
            id="null-name",
        ),
        pytest.param(
            [{"name_en": True, "description_en": "A fictional example."}],
            id="boolean-name",
        ),
        pytest.param(
            [{"name_en": [], "description_en": "A fictional example."}], id="list-name"
        ),
        pytest.param(
            [{"name_en": "Green salad", "description_en": ""}], id="empty-description"
        ),
        pytest.param(
            [{"name_en": "Green salad", "description_en": " \n "}],
            id="blank-description",
        ),
        pytest.param(
            [{"name_en": "Green salad", "description_en": None}], id="null-description"
        ),
        pytest.param(
            [{"name_en": "Green salad", "description_en": {}}], id="mapping-description"
        ),
        pytest.param(
            [{"name_en": "Green salad", "description_en": 42}], id="numeric-description"
        ),
        pytest.param(
            [{"name_en": "N" * 81, "description_en": "A fictional example."}],
            id="oversized-name",
        ),
        pytest.param(
            [{"name_en": "Green salad", "description_en": "D" * 241}],
            id="oversized-description",
        ),
    ],
)
def test_malformed_menu_cannot_be_spoken_as_verified_examples(catalogue, focus, menu):
    catalogue["menu"] = menu
    original = deepcopy(catalogue)

    assert CallTools._render_read_result(catalogue, "en", focus=focus) is None
    assert catalogue == original


@pytest.mark.parametrize("language", ["et", "en", "ru"])
@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("focus", ["menu", "dietary"])
def test_missing_translation_cannot_fall_back_to_another_language(
    catalogue, language, field, focus
):
    del catalogue["menu"][1][field + "_" + language]
    original = deepcopy(catalogue)

    assert CallTools._render_read_result(catalogue, language, focus=focus) is None
    assert catalogue == original


@pytest.mark.parametrize(
    "language,fictional,examples,warning", LANGUAGE_CASES, ids=["et", "en", "ru"]
)
def test_menu_trims_spoken_text_without_mutating_the_catalogue(
    catalogue, language, fictional, examples, warning
):
    catalogue["menu"] = [
        {
            "name_" + language: "  Localized fixture example  ",
            "description_" + language: "  A fictional description.  ",
        }
    ]
    original = deepcopy(catalogue)

    reply = CallTools._render_read_result(catalogue, language, focus="menu")

    assert isinstance(reply, str)
    assert "Localized fixture example: A fictional description." in reply
    assert "  Localized fixture example" not in reply
    assert catalogue == original


@pytest.mark.parametrize(
    "language,fictional,examples,warning", LANGUAGE_CASES, ids=["et", "en", "ru"]
)
def test_valid_bounded_menu_text_is_not_truncated_before_the_safety_caution(
    catalogue, language, fictional, examples, warning
):
    catalogue["menu"] = [
        {"name_" + language: "N" * 80, "description_" + language: "D" * 239 + "."}
        for _ in range(3)
    ]
    original = deepcopy(catalogue)

    reply = CallTools._render_read_result(catalogue, language, focus="menu")

    assert isinstance(reply, str)
    assert reply.count("N" * 80 + ": " + "D" * 239 + ".") == 3
    for fragment in warning:
        assert fragment in reply
    assert len(reply) < 1600
    assert catalogue == original


@pytest.mark.parametrize("focus", ["menu", "dietary"])
@pytest.mark.parametrize(
    "language", ["de", "en-GB", "", None, 42, ["en"], {"language": "en"}]
)
def test_wrong_language_cannot_speak_an_assumed_translation(catalogue, focus, language):
    original = deepcopy(catalogue)

    assert CallTools._render_read_result(catalogue, language, focus=focus) is None
    assert catalogue == original


@pytest.mark.parametrize("focus", ["menu", "dietary"])
@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"synthetic": False}, id="not-synthetic"),
        pytest.param({"synthetic": 1}, id="numeric-synthetic"),
        pytest.param({"synthetic": "true"}, id="text-synthetic"),
        pytest.param({"source": None}, id="missing-source"),
        pytest.param({"source": "demo_stay"}, id="hotel-source"),
        pytest.param({"source": "live_table"}, id="live-source"),
        pytest.param({"tables": None}, id="missing-tables"),
        pytest.param({"tables": {}}, id="tables-not-list"),
    ],
)
def test_non_demo_table_shapes_cannot_acquire_menu_or_dietary_speech(
    catalogue, focus, changes
):
    catalogue.update(changes)
    original = deepcopy(catalogue)

    assert CallTools._render_read_result(catalogue, "en", focus=focus) is None
    assert catalogue == original


@pytest.mark.parametrize("focus", [None, "hours", "services", "tables", "unknown"])
def test_unrelated_focus_cannot_start_a_menu_preview(catalogue, focus):
    original = deepcopy(catalogue)

    reply = CallTools._render_read_result(catalogue, "en", focus=focus)

    # A later restaurant base may already render tables/hours for these focuses.
    assert reply is None or isinstance(reply, str)
    if reply is not None:
        assert "Fictional menu examples" not in reply
        assert "Green salad" not in reply
        assert "Roasted vegetables" not in reply
        assert "Berry dessert" not in reply
    assert catalogue == original


@pytest.mark.parametrize("focus", ["menu", "dietary"])
@pytest.mark.parametrize("result", [None, [], "not a catalogue", 42, True])
def test_non_mapping_read_results_cannot_crash_menu_rendering(result, focus):
    original = deepcopy(result)

    assert CallTools._render_read_result(result, "en", focus=focus) is None
    assert result == original


@pytest.mark.parametrize("focus", ["menu", "dietary"])
@pytest.mark.parametrize(
    "result,expected",
    [
        (
            {
                "room_types": [{"name": "Fixture room", "capacity": 2}],
                "property": {"checkin_time": "15:00", "checkout_time": "11:00"},
            },
            "Fiktiivse hotelli toatüübid: Fixture room, kuni 2 külalist. "
            "Saabumine alates 15:00, lahkumine kuni 11:00. "
            "Mis kuupäevadel soovid peatuda ja mitmele külalisele?",
        ),
        (
            {
                "services": [{"name": "Fixture treatment", "duration": 45}],
                "providers": [
                    {
                        "name": "Fixture therapist",
                        "working_hours": {"monday": {"start": "09:00", "end": "17:00"}},
                    }
                ],
            },
            "Demo spaateenused: Fixture treatment, 45 minutit. "
            "Fixture therapist tööajad: esmaspäev: 09:00–17:00. "
            "Vaba aeg tuleb eraldi kontrollida.",
        ),
        (
            {"offers": []},
            "Soovitud kuupäevadel ja külaliste arvuga vabu demotube ei ole. Kas soovid teisi kuupäevi?",
        ),
        (
            {"slots": []},
            "Selleks kuupäevaks vabu spaademo aegu ei ole. Kas soovid teist kuupäeva?",
        ),
    ],
    ids=["rooms", "spa", "room-offers", "spa-slots"],
)
def test_restaurant_focus_does_not_replace_legacy_read_speech(
    catalogue, result, expected, focus
):
    result = dict(result, menu=catalogue["menu"])
    original = deepcopy(result)

    assert CallTools._render_read_result(result, "et", focus=focus) == expected
    assert result == original
