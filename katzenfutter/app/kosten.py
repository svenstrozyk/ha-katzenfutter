"""Kostenauswertung aus Packungspreisen (€ je Packung).

Kosten einer Mahlzeit = angeboten / Packungsgröße × Preis; der Rest im Napf ist mitbezahlt und wird
zusätzlich als „weggeworfen“ ausgewiesen. Sorten ohne Preis oder Packungsgröße werden nicht mitgerechnet.
"""
import datetime

import zeit

TAGE_AUSWAHL = (30, 90)
TAGE_JE_MONAT = 30.44


def preis_je_g(produkt):
    if produkt["preis"] is None or not produkt["packung_g"]:
        return None
    return produkt["preis"] / produkt["packung_g"]


def je_100_kcal(produkt):
    """€ je 100 kcal; None, wenn Preis, Packung oder kcal fehlen."""
    je_g = preis_je_g(produkt)
    if je_g is None or not produkt["kcal_100g"]:
        return None
    return je_g * 100 / produkt["kcal_100g"] * 100


def auswerten(con, katze_id, tage):
    beginn_tag = zeit.jetzt().astimezone(zeit.BERLIN).date() - datetime.timedelta(days=tage - 1)
    grenze = zeit.tagesbeginn_utc(beginn_tag)
    produkte = {p["id"]: p for p in con.execute("SELECT * FROM produkt")}
    sorten, monate = {}, {}
    gesamt = weggeworfen = 0.0
    ohne_preis = set()

    def buchen(produkt_id, zeitpunkt, menge_g, rest_g=None, snack=False):
        nonlocal gesamt, weggeworfen
        p = produkte[produkt_id]
        je_g = preis_je_g(p)
        if je_g is None or menge_g is None:
            ohne_preis.add(produkt_id)
            return
        betrag = menge_g * je_g
        gesamt += betrag
        if rest_g:
            weggeworfen += rest_g * je_g
        eintrag = sorten.setdefault(produkt_id, {"produkt": p, "betrag": 0.0, "menge_g": 0.0, "snack": snack})
        eintrag["betrag"] += betrag
        eintrag["menge_g"] += menge_g
        monat = zeit.lokal(zeitpunkt).strftime("%Y-%m")
        monate[monat] = monate.get(monat, 0.0) + betrag

    for m in con.execute("SELECT produkt_id, zeit, angeboten_g, rest_g FROM mahlzeit WHERE katze_id = ? AND zeit >= ?",
                         (katze_id, grenze)):
        buchen(m["produkt_id"], m["zeit"], m["angeboten_g"], m["rest_g"])
    for s in con.execute("SELECT s.produkt_id, s.zeit, s.stueck, s.menge_g, p.stueck_g FROM snack s "
                         "JOIN produkt p ON p.id = s.produkt_id WHERE s.katze_id = ? AND s.zeit >= ?", (katze_id, grenze)):
        menge = s["menge_g"] if s["menge_g"] is not None else (s["stueck"] * s["stueck_g"] if s["stueck"] and s["stueck_g"] else None)
        buchen(s["produkt_id"], s["zeit"], menge, snack=True)

    # Tage seit der ersten Erfassung im Zeitraum, damit der Tagesschnitt nicht durch leere Vortage sinkt
    erste = con.execute(
        "SELECT MIN(zeit) FROM (SELECT zeit FROM mahlzeit WHERE katze_id = ? AND zeit >= ? "
        "UNION ALL SELECT zeit FROM snack WHERE katze_id = ? AND zeit >= ?)", (katze_id, grenze, katze_id, grenze),
    ).fetchone()[0]
    tage_mit_daten = None
    if erste:
        tage_mit_daten = (zeit.jetzt().astimezone(zeit.BERLIN).date() - zeit.lokal(erste).date()).days + 1
    je_tag = gesamt / tage_mit_daten if tage_mit_daten else None
    return {
        "tage": tage,
        "gesamt": gesamt,
        "weggeworfen": weggeworfen,
        "je_tag": je_tag,
        "je_monat": je_tag * TAGE_JE_MONAT if je_tag is not None else None,
        "tage_mit_daten": tage_mit_daten,
        "sorten": sorted(sorten.values(), key=lambda e: -e["betrag"]),
        "monate": sorted(monate.items()),
        "ohne_preis": [produkte[i] for i in sorted(ohne_preis)],
    }


def preisvergleich(con):
    """Aktive Sorten mit € je 100 g und € je 100 kcal, günstigste je kcal zuerst."""
    liste = []
    for p in con.execute("SELECT * FROM produkt WHERE status = 'aktiv' ORDER BY marke, sorte"):
        je_g = preis_je_g(p)
        liste.append({"produkt": p, "je_100g": je_g * 100 if je_g is not None else None, "je_100kcal": je_100_kcal(p)})
    return sorted(liste, key=lambda e: (e["je_100kcal"] is None, e["je_100kcal"] or 0))
