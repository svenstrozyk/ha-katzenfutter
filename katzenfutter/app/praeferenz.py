"""Präferenzerkennung: Akzeptanz je Mahlzeit gegen eine gleitende Baseline über alle Futter.

Regeln (CLAUDE.md): a = gefressen / angeboten; Baseline = Mittel von a über alle Futter, 14 Tage;
Gewichte gewogen 1,0 / geschätzt 0,6, erste Mahlzeit nach > 12 h Pause und die ersten zwei Mahlzeiten
einer neuen Sorte halb; Score = Σ w(a − Baseline) / (Σ w + k). Schwellen nach 4–6 Wochen kalibrieren.
"""
import bisect
import datetime

import schwellen
import zeit

K = 3
BASELINE_TAGE = 14
MIN_VERGLEICH = 3
GEWICHT = {"gewogen": 1.0, "geschaetzt": 0.6}
PAUSE_STUNDEN = 12
PAUSE_FAKTOR = 0.5
NEOPHOBIE_MAHLZEITEN = 2
NEOPHOBIE_FAKTOR = 0.5
# Einstufungs- und Einbruchschwellen: schwellen.py (einstellbar)
LIEBLING_N = schwellen.STANDARD["liebling_n"]
EINBRUCH_TAGE = 3

STATUS_TEXT = {"liebling": "Lieblingsfutter", "abgelehnt": "wird nicht gemocht", "neutral": "neutral",
               "zu_wenig": "noch zu wenig Daten"}
BEZUG_TEXT = {"produkt": "Sorte", "marke": "Marke", "textur": "Textur", "protein": "Hauptprotein"}


def mahlzeiten_laden(con, katze_id):
    """Mahlzeiten mit erfasstem Rest (ohne die mit offenem Rest), älteste zuerst."""
    return con.execute(
        "SELECT m.id, m.zeit, m.produkt_id, m.angeboten_g, m.gefressen_g, m.rest_herkunft, m.verweigert, "
        "p.marke, p.textur, p.proteine FROM mahlzeit m JOIN produkt p ON p.id = m.produkt_id "
        "WHERE m.katze_id = ? AND m.rest_g IS NOT NULL ORDER BY m.zeit, m.id",
        (katze_id,),
    ).fetchall()


def bewerten(mahlzeiten, alle_zeiten=None):
    """Je Mahlzeit: a, Baseline, Gewicht. Mahlzeiten ohne Vergleichswerte erhalten Baseline None.

    alle_zeiten: Zeitpunkte aller Mahlzeiten (auch mit offenem Rest) für die Pausenregel.
    Fenster über sortierte Zeiten mit Binärsuche und laufenden Summen (läuft jede Minute für Sensoren).
    """
    zeitpunkte = [datetime.datetime.fromisoformat(m["zeit"]) for m in mahlzeiten]
    akzeptanz = [0.0 if m["verweigert"] else (m["gefressen_g"] or 0) / m["angeboten_g"] for m in mahlzeiten]
    pausen_zeiten = sorted(datetime.datetime.fromisoformat(z) for z in (alle_zeiten or [m["zeit"] for m in mahlzeiten]))
    reihenfolge = sorted(range(len(mahlzeiten)), key=lambda j: zeitpunkte[j])
    sortiert = [zeitpunkte[j] for j in reihenfolge]
    summen = [0.0]
    for j in reihenfolge:
        summen.append(summen[-1] + akzeptanz[j])

    def fenster_mittel(i, von, bis):
        """Mittel von a im Zeitfenster [von, bis] ohne Mahlzeit i; (mittel, anzahl)."""
        links, rechts = bisect.bisect_left(sortiert, von), bisect.bisect_right(sortiert, bis)
        anzahl = rechts - links - 1  # Mahlzeit i liegt immer im Fenster
        if anzahl <= 0:
            return None, 0
        return (summen[rechts] - summen[links] - akzeptanz[i]) / anzahl, anzahl

    fenster = datetime.timedelta(days=BASELINE_TAGE)
    gezaehlt = {}
    ergebnis = []
    for i, m in enumerate(mahlzeiten):
        t = zeitpunkte[i]
        baseline, anzahl = fenster_mittel(i, t - fenster, t)
        if anzahl < MIN_VERGLEICH:
            baseline, _ = fenster_mittel(i, t - fenster, t + fenster)

        w = GEWICHT.get(m["rest_herkunft"], GEWICHT["geschaetzt"])
        vorher = bisect.bisect_left(pausen_zeiten, t) - 1
        if vorher >= 0 and t - pausen_zeiten[vorher] > datetime.timedelta(hours=PAUSE_STUNDEN):
            w *= PAUSE_FAKTOR
        gezaehlt[m["produkt_id"]] = gezaehlt.get(m["produkt_id"], 0) + 1
        if gezaehlt[m["produkt_id"]] <= NEOPHOBIE_MAHLZEITEN:
            w *= NEOPHOBIE_FAKTOR
        ergebnis.append({"mahlzeit": m, "a": akzeptanz[i], "baseline": baseline, "w": w})
    return ergebnis


def _schluessel(m, bezug):
    if bezug == "produkt":
        return [str(m["produkt_id"])]
    if bezug == "marke":
        return [m["marke"].strip()] if m["marke"] else []
    if bezug == "textur":
        text = (m["textur"] or "").strip()
        return [text[:1].upper() + text[1:]] if text else []
    return sorted({p.strip().lower() for p in (m["proteine"] or "").split(",") if p.strip()})


def einstufen(score, n, verweigert, s=None):
    s = s or schwellen.STANDARD
    if verweigert >= s["abgelehnt_verweigert"] or (
            score is not None and n >= s["abgelehnt_n"] and score <= -s["abgelehnt_score"]):
        return "abgelehnt"
    if score is not None and n >= s["liebling_n"] and score >= s["liebling_score"]:
        return "liebling"
    if n < s["liebling_n"]:
        return "zu_wenig"
    return "neutral"


def auswerten(bewertungen, s=None):
    """{(bezug, schluessel): {score, n, verweigert, akzeptanz, status}}"""
    gruppen = {}
    for b in bewertungen:
        for bezug in BEZUG_TEXT:
            for wert in _schluessel(b["mahlzeit"], bezug):
                gruppen.setdefault((bezug, wert), []).append(b)
    ergebnis = {}
    for schluessel, liste in gruppen.items():
        gewertet = [b for b in liste if b["baseline"] is not None]
        summe_w = sum(b["w"] for b in gewertet)
        score = sum(b["w"] * (b["a"] - b["baseline"]) for b in gewertet) / (summe_w + K) if gewertet else None
        verweigert = sum(1 for b in liste if b["mahlzeit"]["verweigert"])
        n = len(liste)
        ergebnis[schluessel] = {
            "score": score, "n": n, "verweigert": verweigert,
            "akzeptanz": sum(b["a"] for b in liste) / n,
            "status": einstufen(score, n, verweigert, s),
        }
    return ergebnis


def akzeptanzeinbruch(bewertungen, jetzt=None, s=None):
    """True, wenn die mittlere Akzeptanz der letzten 3 Tage deutlich (Standard 25 Prozentpunkte) unter den 14 Tagen davor liegt."""
    s = s or schwellen.STANDARD
    jetzt = jetzt or zeit.jetzt()
    grenze = jetzt - datetime.timedelta(days=EINBRUCH_TAGE)
    vorher_grenze = grenze - datetime.timedelta(days=BASELINE_TAGE)
    neu = [b["a"] for b in bewertungen if datetime.datetime.fromisoformat(b["mahlzeit"]["zeit"]) >= grenze]
    alt = [b["a"] for b in bewertungen if vorher_grenze <= datetime.datetime.fromisoformat(b["mahlzeit"]["zeit"]) < grenze]
    if len(neu) < 2 or len(alt) < 5:
        return False
    return sum(alt) / len(alt) - sum(neu) / len(neu) >= s["akzeptanz_einbruch"] / 100


def aktualisieren(con, katze_id):
    """Berechnet alles neu, speichert in praeferenz und liefert (ergebnis, einbruch)."""
    s = schwellen.laden(con)
    mahlzeiten = mahlzeiten_laden(con, katze_id)
    alle_zeiten = [r[0] for r in con.execute("SELECT zeit FROM mahlzeit WHERE katze_id = ?", (katze_id,))]
    bewertungen = bewerten(mahlzeiten, alle_zeiten)
    ergebnis = auswerten(bewertungen, s)
    stand = zeit.iso(zeit.jetzt())
    with con:
        con.execute("DELETE FROM praeferenz WHERE katze_id = ?", (katze_id,))
        con.executemany(
            "INSERT INTO praeferenz (katze_id, bezug, schluessel, score, n, verweigert, akzeptanz, status, stand) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(katze_id, bezug, wert, e["score"], e["n"], e["verweigert"], e["akzeptanz"], e["status"], stand)
             for (bezug, wert), e in ergebnis.items()],
        )
    return ergebnis, akzeptanzeinbruch(bewertungen, s=s)


def einbruch(con, katze_id, s=None):
    """Nur die Einbruch-Prüfung, ohne zu speichern (für Heute und Sensoren)."""
    alle_zeiten = [r[0] for r in con.execute("SELECT zeit FROM mahlzeit WHERE katze_id = ?", (katze_id,))]
    return akzeptanzeinbruch(bewerten(mahlzeiten_laden(con, katze_id), alle_zeiten), s=s or schwellen.laden(con))
