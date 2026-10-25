"""Tagesbilanz für die Heute-Ansicht (Tagesgrenze Europe/Berlin)."""
import datetime

import fachlogik
import gesundheit
import mahlzeiten
import petkit
import praeferenz
import schwellen
import snacks
import verlauf
import zeit

KEINE_AUFNAHME_STUNDEN = 24


def tagesbedarf(katze):
    """MER der Katze oder None, wenn Gewicht oder Zielgewicht (bei Reduktion) fehlen."""
    try:
        return fachlogik.tagesbedarf_kcal(katze["gewicht_aktuell"], katze["aktivitaetsfaktor"], katze["zielgewicht"])
    except (ValueError, TypeError):
        return None


def keine_aufnahme(con, katze_id, stunden=KEINE_AUFNAHME_STUNDEN):
    """True, wenn seit 24 h nachweislich nichts gefressen wurde.

    Mahlzeiten mit offenem Rest zählen als „Aufnahme unbekannt“ und lösen keinen Hinweis aus.
    Ohne jede erfasste Mahlzeit (frische Installation) gibt es keinen Hinweis.
    """
    if con.execute("SELECT 1 FROM mahlzeit WHERE katze_id = ? LIMIT 1", (katze_id,)).fetchone() is None:
        return False
    grenze = zeit.iso(zeit.jetzt() - datetime.timedelta(hours=stunden))
    moeglich = con.execute(
        "SELECT 1 FROM mahlzeit WHERE katze_id = ? AND zeit >= ? AND (rest_g IS NULL OR gefressen_g > 0) LIMIT 1",
        (katze_id, grenze),
    ).fetchone()
    return moeglich is None


def zusammenfassung(con, katze, einst, mer_kcal):
    katze_id = katze["id"]
    s = schwellen.laden(con)
    heutige = con.execute(
        "SELECT m.*, p.sorte, p.kcal_100g, p.feuchte FROM mahlzeit m JOIN produkt p ON p.id = m.produkt_id "
        "WHERE m.katze_id = ? AND m.zeit >= ? ORDER BY m.zeit",
        (katze_id, zeit.tagesbeginn_utc()),
    ).fetchall()
    erfasst = [m for m in heutige if m["rest_g"] is not None]
    offen = [m for m in heutige if m["rest_g"] is None]

    gefressen_kcal = sum(m["kcal"] or 0 for m in erfasst)
    offen_kcal = sum(fachlogik.kcal_aus_menge(m["angeboten_g"], m["kcal_100g"]) for m in offen if m["kcal_100g"] is not None)
    snack_stand = snacks.tagesstand(con, katze_id, einst, mer_kcal)
    kcal_unbekannt = any(m["kcal_100g"] is None for m in heutige) or snack_stand["kcal_unbekannt"]

    futterwasser = sum(fachlogik.futterwasser_ml(m["gefressen_g"], m["feuchte"])
                       for m in erfasst if m["feuchte"] is not None)
    wasser = fachlogik.wasserbilanz(katze["gewicht_aktuell"], futterwasser) if katze["gewicht_aktuell"] else None

    ergebnis = {
        "mer": mer_kcal,
        "gefressen_kcal": gefressen_kcal,
        "gefressen_g": sum(m["gefressen_g"] or 0 for m in erfasst),
        "angeboten_g": sum(m["angeboten_g"] for m in heutige),
        "geschaetzt": any(m["rest_herkunft"] == "geschaetzt" for m in erfasst),
        "offen_kcal": offen_kcal,
        "offene_reste": len(mahlzeiten.offene(con, katze_id)),
        "snack_kcal": snack_stand["kcal"],
        "snack": snack_stand,
        "kcal_unbekannt": kcal_unbekannt,
        "mahlzeiten": len(heutige),
        "wasser": wasser,
        "wasser_feuchte_fehlt": any(m["feuchte"] is None for m in erfasst),
        "keine_aufnahme": keine_aufnahme(con, katze_id, s["keine_aufnahme_stunden"]),
        "keine_aufnahme_stunden": s["keine_aufnahme_stunden"],
        "gesundheit": gesundheit.hinweise(con, katze_id),
        "gewicht_hinweise": verlauf.gewicht_daten(con, katze_id, 7, s)["hinweise"],
        "akzeptanzeinbruch": praeferenz.einbruch(con, katze_id, s),
        "petkit": bool(katze["petkit_besuch_entity"]),
        "toilettengaenge": petkit.toilettengaenge(con, katze_id, 1),
        "viele_gaenge": petkit.viele_gaenge(con, katze_id),
        "ereignisse_heute": [e for e in gesundheit.liste(con, katze_id, tage=1) if e["zeit"] >= zeit.tagesbeginn_utc()],
        "letzte_wiegung": con.execute(
            "SELECT zeit, kg FROM gewicht WHERE katze_id = ? AND verworfen = 0 ORDER BY zeit DESC LIMIT 1", (katze_id,)
        ).fetchone(),
    }
    if mer_kcal:
        verbraucht = gefressen_kcal + snack_stand["kcal"]
        ergebnis["rest_kcal"] = max(mer_kcal - verbraucht - offen_kcal, 0.0)
        ergebnis["anteil"] = min(verbraucht / mer_kcal, 1.5)
        ergebnis["anteil_offen"] = min(offen_kcal / mer_kcal, max(1.5 - ergebnis["anteil"], 0))
        # Vorschlag: Sorte mit angebrochener Packung, sonst zuletzt gefüttert
        vorschlag = next(iter(mahlzeiten.produkte_zum_fuettern(con)), None)
        if vorschlag is not None and vorschlag["kcal_100g"]:
            menge = ergebnis["rest_kcal"] / vorschlag["kcal_100g"] * 100
            ergebnis["vorschlag"] = {
                "produkt": vorschlag,
                "menge_g": menge,
                "packungen": menge / vorschlag["packung_g"] if vorschlag["packung_g"] else None,
            }
    return ergebnis
