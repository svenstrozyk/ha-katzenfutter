"""Auswertung von Deklarationstexten (Live Text vom iPhone, Zutaten aus Open Pet Food Facts).

Liefert nur Vorschläge; gespeichert wird erst nach Prüfung im Formular. Robust gegen typische
Lesefehler und mehrsprachige Etiketten.
"""
import re

# Bezeichnungen auf deutschen Etiketten, längere zuerst (sonst trifft „Fett“ in „Fettgehalt“ falsch)
FELDER = {
    "rohprotein": ["rohprotein", "protein", "eiweiß", "eiweiss"],
    "rohfett": ["rohfett", "fettgehalt", "fett"],
    "rohasche": ["rohasche", "anorganischer stoff", "asche"],
    "rohfaser": ["rohfaser", "faser"],
    "feuchte": ["feuchtigkeit", "feuchtegehalt", "feuchte"],
}
PROTEINE = ["Rind", "Kalb", "Huhn", "Hühnchen", "Geflügel", "Pute", "Truthahn", "Ente", "Gans", "Lamm",
            "Kaninchen", "Wild", "Hirsch", "Schwein", "Pferd", "Lachs", "Thunfisch", "Forelle", "Fisch",
            "Garnelen", "Meeresfrüchte"]
# eine Zahl wie 10,5 / 10.5 / 10 – optional mit Leerzeichen vor dem Komma (OCR)
ZAHL = r"(\d{1,3}(?:\s?[.,]\s?\d{1,2})?)"


def _zahl(text):
    return float(re.sub(r"\s", "", text).replace(",", "."))


def auswerten(text):
    """Sichere Vorschläge aus dem erkannten Text: {feld: wert}."""
    return analysieren(text)[0]


# Zeichen, die Texterkennung häufig statt einer „1“ liest
VERWECHSLER_EINS = r"[\]\[|Il!]"
# Trenner ohne folgende Ziffer („4 ‚ %“): Nachkommastelle verloren
VERLORENE_STELLE = r"\s?[.,‚]\s?(?=%|°/o|o/o)"


def _bestandteil(bereich, feld, namen):
    """(wert, zweifel) für ein Feld; zweifel ist der gelesene Ausschnitt oder None."""
    andere = [n for f, liste in FELDER.items() if f != feld for n in liste]
    for name in namen:
        # Mehrsprachige Etiketten: zwischen Bezeichnung und Wert stehen oft Übersetzungen („Fettgehalt/Teneur …“)
        muster = re.escape(name) + r"(?P<luecke>[^0-9%]{0,90}?)" + ZAHL + r"(?P<verloren>" + VERLORENE_STELLE + r")?"
        for treffer in re.finditer(muster, bereich):
            luecke = treffer.group("luecke")
            # Lücke darf keine andere Bezeichnung enthalten, sonst gehört die Zahl zum nächsten Feld
            if any(n in luecke for n in andere):
                continue
            wert = _zahl(treffer.group(2))
            ausschnitt = bereich[treffer.start():treffer.end() + 2].strip()
            if treffer.group("verloren") or re.search(VERWECHSLER_EINS + r"\s*$", luecke):
                return None, ausschnitt
            if 0 <= wert <= 100:
                return wert, None
            return None, ausschnitt
    return None, None


def analysieren(text):
    """(werte, zweifel): sichere Werte und unsicher gelesene Felder mit Ausschnitt."""
    flach = re.sub(r"\s+", " ", text)
    klein = flach.lower()
    werte, zweifel = {}, {}

    # Analytische Bestandteile; Suche bevorzugt den Abschnitt nach „Analytische Bestandteile“
    beginn = klein.find("analytische")
    bereich = klein[beginn:] if beginn >= 0 else klein
    for feld, namen in FELDER.items():
        wert, ausschnitt = _bestandteil(bereich, feld, namen)
        if wert is not None:
            werte[feld] = wert
        elif ausschnitt:
            zweifel[feld] = ausschnitt

    # Energie: kcal/100 g oder kcal/kg
    kcal = re.search(ZAHL + r"\s*kcal\s*/\s*100\s*g", klein) or re.search(r"(?:energie|brennwert)[^0-9]{0,20}" + ZAHL + r"\s*kcal", klein)
    if kcal:
        wert = _zahl(kcal.group(1))
        if 0 < wert <= 700:
            werte["kcal_100g"] = wert
    else:
        je_kg = re.search(r"(\d{3,4})\s*kcal\s*/\s*kg", klein)
        if je_kg and 100 <= int(je_kg.group(1)) <= 7000:
            werte["kcal_100g"] = int(je_kg.group(1)) / 10

    # Hauptproteine aus der Zusammensetzung (Reihenfolge des Auftretens)
    zusammensetzung = flach
    start = klein.find("zusammensetzung")
    if start >= 0:
        ende = klein.find("analytische", start)
        zusammensetzung = flach[start:ende if ende > start else None]
    gefunden = []
    for protein in PROTEINE:
        stelle = re.search(r"\b" + re.escape(protein), zusammensetzung, re.IGNORECASE)
        if stelle:
            gefunden.append((stelle.start(), protein))
    if gefunden:
        werte["proteine"] = ", ".join(p for _, p in sorted(gefunden))

    if re.search(r"getreidefrei|ohne getreide", klein):
        werte["getreidefrei"] = 1
    if re.search(r"zuckerfrei|ohne zucker|ohne zuckerzusatz", klein):
        werte["zuckerfrei"] = 1
    return werte, zweifel
