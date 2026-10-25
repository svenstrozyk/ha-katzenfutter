"""Bestand: Reichweite aus dem Verbrauch, knappe Sorten, Lieferungen eintragen."""
import datetime

import produkte
import zeit

VERBRAUCH_TAGE = 14


def verbrauch_pro_tag(con, tage=VERBRAUCH_TAGE):
    """Angebotene Gramm je Tag und Sorte (alle Katzen), über die letzten `tage` Tage.

    Zeitraum je Sorte: ab der ersten Mahlzeit im Fenster, mindestens 1 Tag – sonst wirkt eine
    neue Sorte nach einer Mahlzeit wie ein Langläufer.
    """
    jetzt = zeit.jetzt()
    grenze = zeit.iso(jetzt - datetime.timedelta(days=tage))
    ergebnis = {}
    for z in con.execute("SELECT produkt_id, SUM(angeboten_g) AS g, MIN(zeit) AS erste FROM mahlzeit "
                         "WHERE zeit >= ? GROUP BY produkt_id", (grenze,)):
        dauer = (jetzt - datetime.datetime.fromisoformat(z["erste"])).total_seconds() / 86400
        ergebnis[z["produkt_id"]] = z["g"] / max(dauer, 1.0)
    return ergebnis


def uebersicht(con, nachkaufen_tage):
    """Aktive Futter (ohne Snacks) mit Bestand, Reichweite in Tagen und Kennzeichen „knapp“."""
    verbrauch = verbrauch_pro_tag(con)
    zeilen = []
    for p in con.execute(
            "SELECT p.*, COALESCE(b.packungen, 0) AS packungen, b.angebrochen_g FROM produkt p "
            "LEFT JOIN bestand b ON b.produkt_id = p.id WHERE p.status = 'aktiv' AND p.futterart != 'snack' "
            "ORDER BY p.marke, p.linie, p.sorte"):
        g_pro_tag = verbrauch.get(p["id"])
        vorrat_g = (p["packungen"] * p["packung_g"] if p["packung_g"] else 0) + (p["angebrochen_g"] or 0)
        reichweite = vorrat_g / g_pro_tag if g_pro_tag and p["packung_g"] else None
        if p["mindestbestand"] is not None:
            knapp = p["packungen"] <= p["mindestbestand"]
        else:
            knapp = reichweite is not None and reichweite < nachkaufen_tage
        zeilen.append({**dict(p), "bezeichnung": produkte.bezeichnung(p), "g_pro_tag": g_pro_tag,
                       "reichweite_tage": reichweite, "knapp": knapp})
    return zeilen


def auffuellen(con, lieferung):
    """Addiert volle Packungen je Sorte {produkt_id: anzahl}. Rückgabe: Anzahl geänderter Sorten."""
    geaendert = 0
    with con:
        for produkt_id, anzahl in lieferung.items():
            if not anzahl:
                continue
            if con.execute("UPDATE bestand SET packungen = MAX(packungen + ?, 0) WHERE produkt_id = ?",
                           (anzahl, produkt_id)).rowcount == 0:
                con.execute("INSERT INTO bestand (produkt_id, packungen, angebrochen_g) VALUES (?, ?, NULL)",
                            (produkt_id, max(anzahl, 0)))
            geaendert += 1
    return geaendert


def lieferung_aus_formular(form, erlaubte_ids):
    """Liest Felder plus_<id> (ganze Zahlen, auch negativ zum Korrigieren). Rückgabe: (lieferung, fehler)."""
    lieferung = {}
    for produkt_id in erlaubte_ids:
        text = (form.get(f"plus_{produkt_id}") or "").strip().replace("+", "")
        if not text:
            continue
        try:
            anzahl = int(text)
        except ValueError:
            return None, "Packungen bitte als ganze Zahl angeben."
        if not -500 <= anzahl <= 500:
            return None, "Höchstens 500 Packungen je Sorte auf einmal."
        lieferung[produkt_id] = anzahl
    if not lieferung:
        return None, "Keine Packungen eingetragen."
    return lieferung, None
