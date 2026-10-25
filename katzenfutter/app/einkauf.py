"""Einkaufsliste: knappe Sorten als Eintrag in eine To-do-Liste von Home Assistant (todo.*)."""
import json

import requests

HA_API = "http://supervisor/core/api"
PRAEFIX = "Katzenfutter: "


class Fehler(Exception):
    """Einkaufsliste nicht erreichbar oder nicht eingerichtet."""


def laden(con):
    werte = dict(con.execute("SELECT schluessel, wert FROM einstellung WHERE schluessel LIKE 'einkauf_%'").fetchall())
    return {
        "liste": werte.get("einkauf_liste") or "",
        "automatisch": werte.get("einkauf_automatisch") == "1",
        "gemeldet": set(json.loads(werte.get("einkauf_gemeldet") or "[]")),
    }


def speichern(con, liste=None, automatisch=None, gemeldet=None):
    paare = []
    if liste is not None:
        paare.append(("einkauf_liste", liste))
    if automatisch is not None:
        paare.append(("einkauf_automatisch", "1" if automatisch else "0"))
    if gemeldet is not None:
        paare.append(("einkauf_gemeldet", json.dumps(sorted(gemeldet))))
    with con:
        for schluessel, wert in paare:
            con.execute("INSERT INTO einstellung (schluessel, wert) VALUES (?, ?) "
                        "ON CONFLICT (schluessel) DO UPDATE SET wert = excluded.wert", (schluessel, wert))


def aus_formular(form):
    """Rückgabe: (liste, automatisch, fehler)."""
    liste = (form.get("einkauf_liste") or "").strip()
    if liste and not (liste.startswith("todo.") and len(liste) > 5 and " " not in liste):
        return None, None, "Einkaufsliste bitte als Entitäts-ID angeben, z. B. todo.einkaufsliste."
    return liste, form.get("einkauf_automatisch") == "1", None


def eintrag(zeile):
    """Text des Listeneintrags, z. B. „Katzenfutter: Animonda Carny Pute (85 g)“."""
    text = PRAEFIX + zeile["bezeichnung"]
    return text + (f" ({zeile['packung_g']:g} g)" if zeile.get("packung_g") else "")


def _kopf(token):
    return {"Authorization": f"Bearer {token}"}


def listen(token):
    """Verfügbare To-do-Listen als [(entity_id, Name)]."""
    antwort = requests.get(f"{HA_API}/states", headers=_kopf(token), timeout=10)
    antwort.raise_for_status()
    return sorted(((z["entity_id"], z.get("attributes", {}).get("friendly_name") or z["entity_id"])
                   for z in antwort.json() if z["entity_id"].startswith("todo.")), key=lambda t: t[1].lower())


def offene_eintraege(token, liste):
    antwort = requests.post(f"{HA_API}/services/todo/get_items?return_response", headers=_kopf(token), timeout=10,
                            json={"entity_id": liste, "status": "needs_action"})
    antwort.raise_for_status()
    daten = antwort.json().get("service_response", {}).get(liste, {})
    return {e.get("summary", "") for e in daten.get("items", [])}


def hinzufuegen(token, liste, texte):
    """Trägt Texte ein, die noch nicht offen auf der Liste stehen. Rückgabe: (neu, schon_da)."""
    if not liste:
        raise Fehler("Keine Einkaufsliste gewählt (Einstellungen).")
    if not token:
        raise Fehler("Einkaufsliste nur in Home Assistant verfügbar.")
    try:
        vorhanden = offene_eintraege(token, liste)
        neu = [t for t in dict.fromkeys(texte) if t not in vorhanden]
        for text in neu:
            requests.post(f"{HA_API}/services/todo/add_item", headers=_kopf(token), timeout=10,
                          json={"entity_id": liste, "item": text}).raise_for_status()
    except requests.RequestException as exc:
        raise Fehler(f"Einkaufsliste nicht erreichbar ({exc.__class__.__name__}).") from exc
    return len(neu), len(texte) - len(neu)


def automatisch(con, token, zeilen):
    """Trägt neu knapp gewordene Sorten ein (je Knapp-Phase einmal). Rückgabe: Anzahl neuer Einträge."""
    einst = laden(con)
    knapp = {z["id"] for z in zeilen if z["knapp"]}
    if not einst["automatisch"] or not einst["liste"]:
        if einst["gemeldet"] - knapp:
            speichern(con, gemeldet=einst["gemeldet"] & knapp)
        return 0
    neu_knapp = [z for z in zeilen if z["knapp"] and z["id"] not in einst["gemeldet"]]
    anzahl = 0
    if neu_knapp:
        anzahl, _ = hinzufuegen(token, einst["liste"], [eintrag(z) for z in neu_knapp])
    # wieder ausreichend vorrätige Sorten vergessen, damit sie beim nächsten Mal erneut gemeldet werden
    speichern(con, gemeldet=(einst["gemeldet"] & knapp) | {z["id"] for z in neu_knapp})
    return anzahl
