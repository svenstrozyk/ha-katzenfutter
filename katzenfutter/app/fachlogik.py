"""Fachlogik als reine Funktionen (ohne Datenbank und Flask).

Grundlage: Abschnitt „Fachlogik (verbindlich)“ in CLAUDE.md. Ergebnisse werden ungerundet
zurückgegeben; gerundet wird erst in der Anzeige.
"""
import math

# Aktivitätsfaktoren für MER = RER × f. Faktor konservativ wählen, nie automatisch erhöhen.
FAKTOREN = {
    "wohnung_kastriert": 1.2,
    "freigang_kastriert": 1.4,
    "reduktion": 0.8,  # nur auf Zielgewicht anwenden
    "zunahme_min": 1.4,
    "zunahme_max": 1.6,
}

SNACK_ANTEIL_MAX = 0.10

# Anteil des Angebotenen, der als Rest geschätzt wird
REST_STUFEN = {
    "nichts": 0.0,
    "wenig": 0.10,
    "haelfte": 0.50,
    "viel": 0.75,
    "unberuehrt": 1.0,
}

WASSER_ML_PRO_KG = (40, 60)

# Rundungsdifferenzen der Deklaration bis 1 Prozentpunkt werden als NfE 0 akzeptiert
NFE_TOLERANZ = 1.0


def _positiv(wert, name):
    if wert is None or wert <= 0:
        raise ValueError(f"{name} muss größer als 0 sein")


def _prozent(wert, name):
    if wert is None or not 0 <= wert <= 100:
        raise ValueError(f"{name} muss zwischen 0 und 100 % liegen")


# --- Energiebedarf ---------------------------------------------------------

def rer(gewicht_kg):
    """Ruheenergiebedarf in kcal/Tag: 70 × KG^0,75."""
    _positiv(gewicht_kg, "Gewicht")
    return 70 * gewicht_kg ** 0.75


def mer(gewicht_kg, faktor):
    """Erhaltungsenergiebedarf in kcal/Tag: RER × f."""
    _positiv(faktor, "Aktivitätsfaktor")
    return rer(gewicht_kg) * faktor


def tagesbedarf_kcal(gewicht_kg, faktor, zielgewicht_kg=None):
    """MER für den Rechner. Ein Reduktionsfaktor (< 1) gilt nur auf das Zielgewicht."""
    if faktor < 1.0:
        if zielgewicht_kg is None:
            raise ValueError("Reduktion nur mit Zielgewicht – Zielgewicht ist noch offen")
        return mer(zielgewicht_kg, faktor)
    return mer(gewicht_kg, faktor)


# --- Futterbewertung -------------------------------------------------------

def nfe(rohprotein, rohfett, rohasche, rohfaser, feuchte):
    """Stickstofffreie Extraktstoffe in % (Differenzrechnung)."""
    for wert, name in ((rohprotein, "Rohprotein"), (rohfett, "Rohfett"), (rohasche, "Rohasche"),
                       (rohfaser, "Rohfaser"), (feuchte, "Feuchte")):
        _prozent(wert, name)
    rest = 100 - rohprotein - rohfett - rohasche - rohfaser - feuchte
    if rest < -NFE_TOLERANZ:
        raise ValueError(f"Deklaration ergibt mehr als 100 % (NfE {rest:.1f} %) – Werte prüfen")
    return max(rest, 0.0)


def kcal_100g_berechnet(rohprotein, rohfett, rohasche, rohfaser, feuchte):
    """kcal/100 g nach modifizierten Atwater-Faktoren (Kennzeichnung „berechnet“)."""
    return 3.5 * rohprotein + 8.5 * rohfett + 3.5 * nfe(rohprotein, rohfett, rohasche, rohfaser, feuchte)


def trockenmasse(wert_prozent, feuchte):
    """Rechnet einen Nährwert von Frischsubstanz auf Trockenmasse um (in %)."""
    _prozent(wert_prozent, "Nährwert")
    _prozent(feuchte, "Feuchte")
    if feuchte >= 100:
        raise ValueError("Feuchte muss unter 100 % liegen")
    return wert_prozent / (100 - feuchte) * 100


# --- Futtermenge -----------------------------------------------------------

def tagesmenge_g(mer_kcal, kcal_snacks, kcal_100g, anteil=1.0):
    """Hauptfutter in g: (MER − kcal Snacks) × Anteil / (kcal/100 g) × 100, nie negativ."""
    _positiv(kcal_100g, "kcal/100 g")
    if not 0 < anteil <= 1:
        raise ValueError("Anteil muss zwischen 0 und 1 liegen")
    return max(mer_kcal - kcal_snacks, 0.0) * anteil / kcal_100g * 100


def packungsplan(menge_g, packung_g, angebrochen_g=0.0):
    """Teilt eine Menge auf angebrochene und neue Packungen auf.

    Zuerst wird die angebrochene Packung verbraucht. Rückgabe:
    aus_angebrochen_g, neue_packungen, rest_angebrochen_g (Bestand danach).
    """
    _positiv(packung_g, "Packungsgröße")
    if menge_g < 0 or angebrochen_g < 0:
        raise ValueError("Menge und angebrochene Packung dürfen nicht negativ sein")
    aus_angebrochen = min(angebrochen_g, menge_g)
    offen = menge_g - aus_angebrochen
    neue = math.ceil(offen / packung_g) if offen > 0 else 0
    if neue:
        rest = neue * packung_g - offen
    else:
        rest = angebrochen_g - aus_angebrochen
    return {"aus_angebrochen_g": aus_angebrochen, "neue_packungen": neue, "rest_angebrochen_g": rest}


# --- Rest und Aufnahme -----------------------------------------------------

def rest_aus_stufe(angeboten_g, stufe):
    """Geschätzter Rest in g aus einer Schätzstufe."""
    _positiv(angeboten_g, "Angebotene Menge")
    if stufe not in REST_STUFEN:
        raise ValueError(f"Unbekannte Schätzstufe: {stufe}")
    return angeboten_g * REST_STUFEN[stufe]


def gefressen_g(angeboten_g, rest_g):
    """Gefressen = angeboten − Rest."""
    _positiv(angeboten_g, "Angebotene Menge")
    if rest_g < 0 or rest_g > angeboten_g:
        raise ValueError("Rest muss zwischen 0 und der angebotenen Menge liegen")
    return angeboten_g - rest_g


def kcal_aus_menge(menge_g, kcal_100g):
    return menge_g * kcal_100g / 100


# --- Snacks ----------------------------------------------------------------

def snack_anteil(kcal_snacks, mer_kcal):
    _positiv(mer_kcal, "Tagesbedarf")
    return kcal_snacks / mer_kcal


def snack_warnung(kcal_snacks, mer_kcal):
    """True ab 10 % der Tageskalorien aus Snacks."""
    return snack_anteil(kcal_snacks, mer_kcal) >= SNACK_ANTEIL_MAX


# --- Wasser ----------------------------------------------------------------

def futterwasser_ml(gefressen, feuchte):
    """Wasser aus dem Futter (1 g Wasser ≈ 1 ml)."""
    _prozent(feuchte, "Feuchte")
    return gefressen * feuchte / 100


def wasserrichtwert_ml(gewicht_kg):
    """Richtwert Gesamtwasser pro Tag als (min, max) in ml."""
    _positiv(gewicht_kg, "Gewicht")
    return WASSER_ML_PRO_KG[0] * gewicht_kg, WASSER_ML_PRO_KG[1] * gewicht_kg


def wasserbilanz(gewicht_kg, futterwasser, getrunken_ml=None):
    """Gesamtwasser = Futterwasser + Getrunkenes; Getrunkenes ist ohne Trinkbrunnen unbekannt."""
    minimum, maximum = wasserrichtwert_ml(gewicht_kg)
    gesamt = futterwasser + (getrunken_ml or 0)
    return {
        "gesamt_ml": gesamt,
        "richtwert_min_ml": minimum,
        "richtwert_max_ml": maximum,
        "getrunken_bekannt": getrunken_ml is not None,
        "unter_richtwert": gesamt < minimum,
    }
