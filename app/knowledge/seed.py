"""Seeded ET hotel/spa FAQ docs (descriptive only — never prices)."""

SEED_DOCS = [
    {
        "doc_id": "checkin",
        "title": "Saabumine ja lahkumine",
        "text": "Saabumine alates kell 15.00, lahkumine hiljemalt kell 12.00. "
        "Hiline lahkumine kokkuleppel vastuvõtuga.",
        "lang": "et",
    },
    {
        "doc_id": "breakfast",
        "title": "Hommikusöök",
        "text": "Hommikusööki serveeritakse kell 7.00–10.30 restoranis. "
        "Eritoidust teatage palun ette.",
        "lang": "et",
    },
    {
        "doc_id": "parking",
        "title": "Parkimine",
        "text": "Parkimine hotelli ees on külalistele tasuta. Kohti on piiratud arv.",
        "lang": "et",
    },
    {
        "doc_id": "spa",
        "title": "Spaa",
        "text": "Spaa on avatud kell 9.00–21.00. Protseduuridele palume "
        "broneerida aja ette.",
        "lang": "et",
    },
    {
        "doc_id": "cancel",
        "title": "Broneeringu muutmine",
        "text": "Broneeringut saab muuta või tühistada kuni 24 tundi enne "
        "saabumist helistades vastuvõttu.",
        "lang": "et",
    },
]


def seed(db, force: bool = False) -> int:
    """Insert seed docs once (or always when force). Returns count."""
    from . import ingest

    if not force:
        try:
            count = db.execute("SELECT COUNT(*) FROM faq").fetchone()[0]
        except Exception:
            count = 0
        if count:
            return 0
    return ingest(db, SEED_DOCS)
