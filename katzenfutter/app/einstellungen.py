"""Haushaltseinstellungen in der Tabelle einstellung (Personen, Snack-Limit der Kinder)."""
import json

ROLLEN = [("erwachsen", "Erwachsen"), ("kind", "Kind")]


def laden(con):
    werte = dict(con.execute("SELECT schluessel, wert FROM einstellung").fetchall())
    limit = werte.get("snack_limit_kinder")
    return {
        "personen": json.loads(werte.get("personen") or "[]"),
        "snack_limit_kinder": int(limit) if limit not in (None, "") else None,
    }


def speichern(con, personen, snack_limit_kinder):
    with con:
        for schluessel, wert in (
            ("personen", json.dumps(personen, ensure_ascii=False)),
            ("snack_limit_kinder", "" if snack_limit_kinder is None else str(snack_limit_kinder)),
        ):
            con.execute(
                "INSERT INTO einstellung (schluessel, wert) VALUES (?, ?) "
                "ON CONFLICT (schluessel) DO UPDATE SET wert = excluded.wert",
                (schluessel, wert),
            )


def aus_formular(form):
    """Liest die Personenzeilen und das Limit. Rückgabe: (personen, limit, fehler)."""
    personen, namen = [], set()
    for name, rolle, ha_name in zip(form.getlist("name"), form.getlist("rolle"), form.getlist("ha_name")):
        name, ha_name = name.strip(), ha_name.strip()
        if not name:
            continue
        if name.lower() in namen:
            return None, None, f"„{name}“ ist doppelt eingetragen."
        if rolle not in dict(ROLLEN):
            return None, None, "Unbekannte Rolle."
        namen.add(name.lower())
        personen.append({"name": name, "rolle": rolle, "ha_name": ha_name})
    if personen and not any(p["rolle"] == "erwachsen" for p in personen):
        return None, None, "Mindestens eine Person muss erwachsen sein."
    text = (form.get("snack_limit_kinder") or "").strip()
    if not text:
        return personen, None, None
    if not text.isdigit() or int(text) > 50:
        return None, None, "Snack-Limit bitte als ganze Zahl von 0 bis 50 angeben (leer = kein Limit)."
    return personen, int(text), None


def _kandidaten(ha_benutzer):
    """Vergleichswerte für den angemeldeten Benutzer: Anzeigename, Benutzername, Vorname (klein)."""
    namen = [ha_benutzer] if isinstance(ha_benutzer, str) else list(ha_benutzer or [])
    werte = []
    for name in namen:
        name = (name or "").strip().lower()
        if name and name not in werte:
            werte.append(name)
    return werte


def person_zu_benutzer(einst, ha_benutzer):
    """Ordnet den angemeldeten HA-Benutzer einer Person zu. None, wenn unbekannt.

    Reihenfolge: eingetragener HA-Benutzer, Name, dann Vorname des HA-Anzeigenamens
    („Alex Muster“ → „Alex“), damit niemand doppelt erscheint.
    """
    kandidaten = _kandidaten(ha_benutzer)
    for p in einst["personen"]:
        if p["ha_name"] and p["ha_name"].lower() in kandidaten:
            return p
    for p in einst["personen"]:
        if p["name"].lower() in kandidaten:
            return p
    vornamen = {k.split()[0] for k in kandidaten if k.split()}
    treffer = [p for p in einst["personen"] if p["name"].lower() in vornamen]
    return treffer[0] if len(treffer) == 1 else None


def ist_kind(einst, name):
    return any(p["name"] == name and p["rolle"] == "kind" for p in einst["personen"])


def darf_aendern(einst, ha_benutzer):
    """Ohne Personen darf jeder ändern; danach nur Erwachsene."""
    if not einst["personen"]:
        return True
    person = person_zu_benutzer(einst, ha_benutzer)
    return person is not None and person["rolle"] == "erwachsen"


def auswahl(einst, ha_benutzer):
    """Namen für „gegeben von“ und die Vorbelegung (angemeldeter Benutzer)."""
    person = person_zu_benutzer(einst, ha_benutzer)
    anzeigename = ha_benutzer if isinstance(ha_benutzer, str) else next(iter(ha_benutzer), "unbekannt")
    vorbelegt = person["name"] if person else anzeigename
    namen = [p["name"] for p in einst["personen"]]
    if vorbelegt not in namen:
        namen.insert(0, vorbelegt)
    return namen, vorbelegt
