"""Verlauf: Gewichtstrend und -hinweise, kcal je Tag, Diagrammdaten (SVG-Koordinaten)."""
import datetime
import statistics

import schwellen
import zeit

TAGE_AUSWAHL = (7, 30, 90)
AUSREISSER_ANTEIL = 0.05
# Gewichtshinweise: Schwellen in schwellen.py (einstellbar); Hinweise, keine Diagnosen
REFERENZ_TOLERANZ_TAGE = 3
PETKIT_LUECKE_TAGE = 3


def tag_lokal(text):
    return zeit.lokal(text).date()


def heute_lokal():
    return zeit.jetzt().astimezone(zeit.BERLIN).date()


# --- Gewicht ---------------------------------------------------------------

def ist_ausreisser(kg, referenz_median):
    """Abweichung > 5 % zum 7-Tage-Median (Regel für PetKit-Werte)."""
    return referenz_median is not None and abs(kg - referenz_median) / referenz_median > AUSREISSER_ANTEIL


def tagesmediane(wiegungen):
    """{datum: median kg} aus Wiegungen (verworfene ausgeschlossen)."""
    je_tag = {}
    for w in wiegungen:
        if not w["verworfen"]:
            je_tag.setdefault(tag_lokal(w["zeit"]), []).append(w["kg"])
    return {tag: statistics.median(werte) for tag, werte in sorted(je_tag.items())}


def trend(mediane):
    """Gleitender 7-Tage-Mittelwert der Tagesmediane: {datum: kg} für jeden Tag mit Wert."""
    ergebnis = {}
    for tag in mediane:
        fenster = [kg for t, kg in mediane.items() if tag - datetime.timedelta(days=6) <= t <= tag]
        ergebnis[tag] = sum(fenster) / len(fenster)
    return ergebnis


def _referenz(trendwerte, ziel):
    """Trendwert am nächsten zum Zieldatum, höchstens 3 Tage entfernt."""
    kandidaten = [(abs((t - ziel).days), t) for t in trendwerte if abs((t - ziel).days) <= REFERENZ_TOLERANZ_TAGE]
    return trendwerte[min(kandidaten)[1]] if kandidaten else None


def gewichtshinweise(trendwerte, petkit_letzte=None, s=None):
    """Liste von Texten; vergleicht den letzten Trendwert mit 7 und 28 Tagen vorher."""
    s = s or schwellen.STANDARD
    verlust_woche = s["gewicht_verlust_woche"] / 100
    verlust_monat = s["gewicht_verlust_4wochen"] / 100
    zunahme_monat = s["gewicht_zunahme_4wochen"] / 100
    hinweise = []
    if petkit_letzte is not None and (heute_lokal() - petkit_letzte).days >= PETKIT_LUECKE_TAGE:
        hinweise.append(f"Seit {PETKIT_LUECKE_TAGE} Tagen kein Gewicht von der Toilette – Gerät prüfen.")
    if not trendwerte:
        return hinweise
    letzter_tag = max(trendwerte)
    aktuell = trendwerte[letzter_tag]
    woche = _referenz(trendwerte, letzter_tag - datetime.timedelta(days=7))
    monat = _referenz(trendwerte, letzter_tag - datetime.timedelta(days=28))
    if woche and (woche - aktuell) / woche > verlust_woche:
        hinweise.append(f"Gewichtsverlust {((woche - aktuell) / woche * 100):.1f} % in einer Woche – beobachten,"
                        " bei Fortsetzung Tierarzt fragen.".replace(".", ",", 1))
    if monat and (monat - aktuell) / monat > verlust_monat:
        hinweise.append(f"Gewichtsverlust {((monat - aktuell) / monat * 100):.1f} % in 4 Wochen – bitte Tierarzt fragen."
                        .replace(".", ",", 1))
    if monat and (aktuell - monat) / monat > zunahme_monat:
        hinweise.append(f"Gewichtszunahme {((aktuell - monat) / monat * 100):.1f} % in 4 Wochen – Futtermenge und Snacks prüfen."
                        .replace(".", ",", 1))
    return hinweise


def gewicht_daten(con, katze_id, tage, s=None):
    """Wiegungen im Zeitraum plus 7 Tage Vorlauf für den Trend; Hinweise immer über 35 Tage."""
    vorlauf = max(tage, 28) + 7
    grenze = zeit.iso(zeit.jetzt() - datetime.timedelta(days=vorlauf))
    wiegungen = con.execute(
        "SELECT zeit, kg, quelle, verworfen FROM gewicht WHERE katze_id = ? AND zeit >= ? ORDER BY zeit",
        (katze_id, grenze),
    ).fetchall()
    mediane = tagesmediane(wiegungen)
    trendwerte = trend(mediane)
    petkit = [w for w in wiegungen if w["quelle"] == "petkit" and not w["verworfen"]]
    beginn = heute_lokal() - datetime.timedelta(days=tage - 1)
    return {
        "mediane": {t: kg for t, kg in mediane.items() if t >= beginn},
        "trend": {t: kg for t, kg in trendwerte.items() if t >= beginn},
        "hinweise": gewichtshinweise(trendwerte, tag_lokal(petkit[-1]["zeit"]) if petkit else None,
                                     s or schwellen.laden(con)),
        "wiegungen": [w for w in wiegungen if tag_lokal(w["zeit"]) >= beginn],
    }


def wiegungen_letzte(con, katze_id, anzahl=10):
    return con.execute("SELECT id, zeit, kg, quelle, verworfen FROM gewicht WHERE katze_id = ? ORDER BY zeit DESC, id DESC "
                       "LIMIT ?", (katze_id, anzahl)).fetchall()


def wiegung_umschalten(con, katze_id, gewicht_id):
    """Wiegung verwerfen oder wieder zulassen; Profilgewicht folgt der jüngsten gültigen Wiegung."""
    with con:
        con.execute("UPDATE gewicht SET verworfen = 1 - verworfen WHERE id = ? AND katze_id = ?", (gewicht_id, katze_id))
        juengste = con.execute("SELECT kg FROM gewicht WHERE katze_id = ? AND verworfen = 0 ORDER BY zeit DESC, id DESC "
                               "LIMIT 1", (katze_id,)).fetchone()
        con.execute("UPDATE katze SET gewicht_aktuell = ? WHERE id = ?", (juengste["kg"] if juengste else None, katze_id))


def gewicht_eintragen(con, katze, kg, tag):
    """Manuelle Wiegung; aktuelles Gewicht im Profil nur, wenn es die jüngste Wiegung ist."""
    if tag == heute_lokal():
        zeitpunkt = zeit.jetzt()
    else:
        zeitpunkt = datetime.datetime.combine(tag, datetime.time(12, 0), tzinfo=zeit.BERLIN)
    with con:
        con.execute("INSERT INTO gewicht (katze_id, zeit, kg, quelle) VALUES (?, ?, ?, 'manuell')",
                    (katze["id"], zeit.iso(zeitpunkt), kg))
        juengste = con.execute(
            "SELECT kg FROM gewicht WHERE katze_id = ? AND verworfen = 0 ORDER BY zeit DESC, id DESC LIMIT 1",
            (katze["id"],)).fetchone()
        con.execute("UPDATE katze SET gewicht_aktuell = ? WHERE id = ?", (juengste["kg"], katze["id"]))


# --- Energie je Tag --------------------------------------------------------

def kcal_tage(con, katze_id, tage):
    """[{tag, futter, snacks, geschaetzt, offen}] für jeden Kalendertag im Zeitraum (Berlin)."""
    beginn = heute_lokal() - datetime.timedelta(days=tage - 1)
    grenze = zeit.tagesbeginn_utc(beginn)
    tage_daten = {beginn + datetime.timedelta(days=i): {"futter": 0.0, "snacks": 0.0, "geschaetzt": False, "offen": 0}
                  for i in range(tage)}
    for m in con.execute("SELECT zeit, kcal, rest_g, rest_herkunft FROM mahlzeit WHERE katze_id = ? AND zeit >= ?",
                         (katze_id, grenze)):
        eintrag = tage_daten.get(tag_lokal(m["zeit"]))
        if eintrag is None:
            continue
        if m["rest_g"] is None:
            eintrag["offen"] += 1
        else:
            eintrag["futter"] += m["kcal"] or 0
            eintrag["geschaetzt"] |= m["rest_herkunft"] == "geschaetzt"
    for s in con.execute("SELECT zeit, kcal FROM snack WHERE katze_id = ? AND zeit >= ?", (katze_id, grenze)):
        eintrag = tage_daten.get(tag_lokal(s["zeit"]))
        if eintrag is not None:
            eintrag["snacks"] += s["kcal"] or 0
    return [dict(tag=t, **d) for t, d in tage_daten.items()]


# --- Diagramme (SVG-Koordinaten) -------------------------------------------

BREITE, HOEHE = 600, 220
RAND = {"links": 44, "rechts": 12, "oben": 12, "unten": 28}


def _x_achse(tage):
    beginn = heute_lokal() - datetime.timedelta(days=tage - 1)
    innen = BREITE - RAND["links"] - RAND["rechts"]
    schritt = innen / tage

    def x(tag):
        return RAND["links"] + ((tag - beginn).days + 0.5) * schritt

    abstand = 1 if tage <= 7 else 7 if tage <= 30 else 14
    ticks = [(x(beginn + datetime.timedelta(days=i)), (beginn + datetime.timedelta(days=i)).strftime("%d.%m."))
             for i in range(tage - 1, -1, -abstand)]
    return x, schritt, ticks


def _y_skala(minimum, maximum, anzahl=4):
    """Runde Achsenwerte und Abbildung auf Pixel."""
    if maximum - minimum < 1e-9:
        minimum, maximum = minimum - 0.5, maximum + 0.5
    roh = (maximum - minimum) / (anzahl - 1)
    stufe = min((s for s in (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200) if s >= roh), default=500)
    unten = (minimum // stufe) * stufe
    oben = -((-maximum) // stufe) * stufe
    innen = HOEHE - RAND["oben"] - RAND["unten"]

    def y(wert):
        return RAND["oben"] + innen - (wert - unten) / (oben - unten) * innen

    werte, w = [], unten
    while w <= oben + stufe / 2:
        werte.append(round(w, 4))
        w += stufe
    return y, [(y(v), v) for v in werte]


def gewicht_diagramm(daten, tage):
    if not daten["mediane"]:
        return None
    x, _, xticks = _x_achse(tage)
    alle = list(daten["mediane"].values()) + list(daten["trend"].values())
    y, yticks = _y_skala(min(alle) - 0.05, max(alle) + 0.05)
    return {
        "punkte": [{"x": x(t), "y": y(kg), "tag": t, "kg": kg} for t, kg in daten["mediane"].items()],
        "linie": " ".join(f"{x(t):.1f},{y(kg):.1f}" for t, kg in daten["trend"].items()),
        "xticks": xticks, "yticks": yticks, "breite": BREITE, "hoehe": HOEHE, "rand": RAND,
    }


def kcal_diagramm(reihe, tage, mer):
    if not any(t["futter"] or t["snacks"] for t in reihe):
        return None
    x, schritt, xticks = _x_achse(tage)
    hoechster = max([t["futter"] + t["snacks"] for t in reihe] + [mer or 0])
    y, yticks = _y_skala(0, hoechster * 1.05)
    breite_balken = max(min(schritt * 0.7, 28), 2)
    balken = []
    for t in reihe:
        mitte = x(t["tag"])
        y_futter = y(t["futter"])
        y_summe = y(t["futter"] + t["snacks"])
        balken.append({
            "x": mitte - breite_balken / 2, "w": breite_balken, "tag": t["tag"],
            "futter": t["futter"], "snacks": t["snacks"], "geschaetzt": t["geschaetzt"], "offen": t["offen"],
            "y_futter": y_futter, "h_futter": y(0) - y_futter,
            # 2 px Abstand zwischen den gestapelten Segmenten
            "y_snack": y_summe, "h_snack": max(y_futter - y_summe - 2, 0) if t["snacks"] else 0,
        })
    return {"balken": balken, "mer_y": y(mer) if mer else None, "mer": mer, "xticks": xticks, "yticks": yticks,
            "breite": BREITE, "hoehe": HOEHE, "rand": RAND, "null_y": y(0)}
