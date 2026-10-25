"""Katzenfutter-Add-on: Flask-App hinter Home-Assistant-Ingress.

Routen für Heute, Füttern, Futter, Verlauf, Katze und Einstellungen; Hintergrunddienste für
MQTT-Sensoren, Mitteilungen und PetKit. Fachlogik in eigenen Modulen (fachlogik, mahlzeiten, …).
"""
import datetime
import decimal
import json
import logging
import os
import re
import threading
import time

import requests
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

import benachrichtigung
import datenbank
import ean_daten
import einstellungen
import fachlogik
import gesundheit
import heute as heute_modul
import kosten as kosten_modul
import mahlzeiten
import mqtt_sensoren
import petkit
import praeferenz
import produkte
import schwellen
import snacks
import texterkennung
import verlauf as verlauf_modul
import zeit

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "katzenfutter.db")
OPTIONS_PATH = os.path.join(DATA_DIR, "options.json")
FOTO_ORDNER = os.path.join(DATA_DIR, "fotos")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
# Ingress-Proxy des Supervisors; Entwicklungsmodus erlaubt lokale Tests
ALLOWED_PEERS = {"172.30.32.2"}
DEV_MODE = os.environ.get("DEV_MODE") == "1"
# Tageskopien im Konfigurationsordner des Add-ons (per Samba/SSH unter addon_configs erreichbar)
SICHERUNG_ORDNER = os.environ.get("SICHERUNG_DIR") or (
    "/config/sicherung" if os.path.isdir("/config") and not DEV_MODE else os.path.join(DATA_DIR, "sicherung"))


class IngressPrefix:
    """Setzt SCRIPT_NAME aus X-Ingress-Path, damit url_for() unter Ingress korrekte Pfade liefert."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_INGRESS_PATH")
        if prefix:
            environ["SCRIPT_NAME"] = prefix.rstrip("/")
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
app.wsgi_app = IngressPrefix(app.wsgi_app)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # Fotos bis 15 MB


_wiederhergestellt = datenbank.wiederherstellen(DB_PATH, SICHERUNG_ORDNER, zeit.jetzt().strftime("%Y%m%d-%H%M%S"))
if _wiederhergestellt == "eingespielt":
    logging.getLogger("katzenfutter.sicherung").warning("Datenbank aus %s eingespielt", datenbank.WIEDERHERSTELLEN)
elif _wiederhergestellt == "ungueltig":
    logging.getLogger("katzenfutter.sicherung").error("%s ist keine gültige Datenbank, nicht eingespielt",
                                                      datenbank.WIEDERHERSTELLEN)
datenbank.migrieren(DB_PATH)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def db():
    return datenbank.verbinden(DB_PATH)




def options():
    try:
        with open(OPTIONS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def ha_user():
    return (
        request.headers.get("X-Remote-User-Display-Name")
        or request.headers.get("X-Remote-User-Name")
        # nur im Entwicklungsmodus (Screenshots, lokale Tests ohne Ingress)
        or (os.environ.get("DEV_BENUTZER") if DEV_MODE else None)
        or "unbekannt"
    )


def ha_benutzer():
    """Anzeigename und Benutzername aus Ingress, für die Zuordnung zu Personen im Haushalt."""
    return [ha_user(), request.headers.get("X-Remote-User-Name") or ""]


# MQTT-Sensoren nur im Add-on (Supervisor-Token oder Broker in den Optionen), nicht in Tests
mqtt_dienst = None
if not DEV_MODE and (SUPERVISOR_TOKEN or options().get("mqtt_host")):
    mqtt_dienst = mqtt_sensoren.Dienst(DB_PATH, SUPERVISOR_TOKEN, options)
    mqtt_dienst.start()

# Rest-Erinnerung per Mitteilung; Panel-Pfad aus dem Hostnamen (4f1ea0a0-katzenfutter → /4f1ea0a0_katzenfutter)
PANEL_PFAD = "/" + os.environ.get("HOSTNAME", "").replace("-", "_") if os.environ.get("HOSTNAME") else "/"
mitteilung_dienst = None
if not DEV_MODE and SUPERVISOR_TOKEN:
    mitteilung_dienst = benachrichtigung.Dienst(
        DB_PATH, SUPERVISOR_TOKEN, options, PANEL_PFAD,
        bei_aenderung=lambda: mqtt_dienst.aenderung() if mqtt_dienst else None,
    )
    mitteilung_dienst.start()


def petkit_abgleich_schleife():
    """Alle 5 Minuten PetKit-Sensoren abgleichen; bei neuen Werten Sensoren aktualisieren."""
    log = logging.getLogger("katzenfutter.petkit")
    while True:
        try:
            con = db()
            try:
                ergebnis = petkit.abgleichen(con, SUPERVISOR_TOKEN)
            finally:
                con.close()
            neu = sum(z["besuche"] + z["gewichte"] + z["verworfen"] for z in ergebnis.values())
            if neu:
                log.info("PetKit übernommen: %s", ergebnis)
                if mqtt_dienst:
                    mqtt_dienst.aenderung()
        except requests.RequestException as exc:
            log.warning("PetKit-Abgleich nicht möglich (%s), neuer Versuch in 5 Minuten", exc)
        except Exception:
            log.exception("PetKit-Abgleich fehlgeschlagen")
        time.sleep(300)


if not DEV_MODE and SUPERVISOR_TOKEN:
    threading.Thread(target=petkit_abgleich_schleife, name="petkit", daemon=True).start()


def sicherung_schleife():
    """Stündlich prüfen, ob die Tageskopie (Europe/Berlin) existiert; 7 Tage aufbewahren."""
    log = logging.getLogger("katzenfutter.sicherung")
    while True:
        try:
            neu = datenbank.sicherung(DB_PATH, SICHERUNG_ORDNER, zeit.jetzt().astimezone(zeit.BERLIN).date())
            if neu:
                log.info("Datenbank gesichert: %s", neu)
        except Exception:
            log.exception("Sicherung der Datenbank fehlgeschlagen")
        time.sleep(3600)


if not DEV_MODE:
    threading.Thread(target=sicherung_schleife, name="sicherung", daemon=True).start()


def mitteilung_entfernen(mahlzeit_id):
    """Rest wurde in der App erfasst: Erinnerung auf allen Geräten entfernen (im Hintergrund)."""
    if mitteilung_dienst:
        threading.Thread(target=mitteilung_dienst.zuruecknehmen, args=(mahlzeit_id,), daemon=True).start()


@app.after_request
def sensoren_aktualisieren(antwort):
    """Nach jeder erfolgreichen Erfassung den Zustand sofort senden."""
    if mqtt_dienst and request.method == "POST" and antwort.status_code < 400:
        mqtt_dienst.aenderung()
    return antwort


@app.before_request
def only_ingress():
    if not DEV_MODE and request.remote_addr not in ALLOWED_PEERS:
        abort(403)


# Änderungen an Stammdaten nur für Erwachsene (ohne angelegte Personen: alle).
# Kinder dürfen füttern, Rest eintragen, Snacks geben, Gesundheit melden und alles ansehen.
NUR_ERWACHSENE = {"katze", "katze_neu", "katze_entfernen", "produkt", "sperren", "verlauf", "wiegung_umschalten",
                  "mahlzeit_loeschen", "einstellungen_seite"}


def darf_aendern():
    con = db()
    try:
        return einstellungen.darf_aendern(einstellungen.laden(con), ha_benutzer())
    finally:
        con.close()


@app.before_request
def rechte_pruefen():
    if request.method == "POST" and request.endpoint in NUR_ERWACHSENE and not darf_aendern():
        abort(403)


@app.errorhandler(403)
def verboten(_fehler):
    return ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<body style='font: 17px -apple-system, system-ui, sans-serif; padding: 24px;'>"
            "<h1 style='font-size: 24px;'>Nicht erlaubt</h1><p>Das dürfen nur Erwachsene ändern.</p>"
            "<p><a href='./'>Zur Startseite</a></p></body>", 403)


def zahl(text):
    """Liest eine Zahl aus einem Formularfeld; Komma als Dezimaltrenner erlaubt, leer = None."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    return float(text)


@app.template_filter("de")
def format_de(wert, stellen=0):
    """Deutsche Zahl, kaufmännisch gerundet (42,5 → 43 statt 42)."""
    if wert is None:
        return "–"
    gerundet = decimal.Decimal(str(wert)).quantize(decimal.Decimal(1).scaleb(-stellen), decimal.ROUND_HALF_UP)
    return f"{gerundet:,.{stellen}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


@app.template_filter("gramm")
def format_gramm(wert):
    """Gramm ohne Nachkomma, außer es gibt eins (85 g, 42,5 g)."""
    if wert is None:
        return "–"
    return format_de(wert, 0 if float(wert).is_integer() else 1)


KATZE_COOKIE = "katzenfutter_katze"


def aktive_katze(con):
    """Gewählte Katze (Cookie je Gerät), sonst die erste aktive."""
    gewaehlt = request.cookies.get(KATZE_COOKIE, type=int) if request else None
    if gewaehlt:
        tier = con.execute("SELECT * FROM katze WHERE id = ? AND aktiv = 1", (gewaehlt,)).fetchone()
        if tier:
            return tier
    return con.execute("SELECT * FROM katze WHERE aktiv = 1 ORDER BY id LIMIT 1").fetchone()


@app.context_processor
def katzen_auswahl():
    """Für den Umschalter oben auf jeder Seite (nur sichtbar bei mehreren Katzen)."""
    con = db()
    try:
        return {"alle_katzen": con.execute("SELECT id, name FROM katze WHERE aktiv = 1 ORDER BY id").fetchall(),
                "aktuelle_katze": aktive_katze(con),
                "darf_aendern": einstellungen.darf_aendern(einstellungen.laden(con), ha_benutzer())}
    finally:
        con.close()


def katze_merken(antwort, katze_id):
    # Pfad = Ingress-Präfix, damit das Cookie nicht für ganz Home Assistant gilt
    antwort.set_cookie(KATZE_COOKIE, str(katze_id), max_age=365 * 24 * 3600, path=(request.script_root or "") + "/",
                       samesite="Lax", httponly=True)
    return antwort


@app.post("/katze_waehlen")
def katze_waehlen():
    con = db()
    try:
        tier = con.execute("SELECT id FROM katze WHERE id = ? AND aktiv = 1",
                           (request.form.get("id", type=int),)).fetchone()
    finally:
        con.close()
    if tier is None:
        abort(404)
    erlaubt = {"heute": "heute", "fuettern": "fuettern", "futter": "futter", "verlauf": "verlauf", "katze": "katze",
               "snack": "snack", "gesundheit": "gesundheit_seite", "kosten": "kosten"}
    ziel = erlaubt.get(request.form.get("zurueck"), "heute")
    return katze_merken(redirect(url_for(ziel)), tier["id"])


@app.post("/katze_entfernen")
def katze_entfernen():
    """Katze ausblenden (aktiv = 0); Daten bleiben erhalten. Die letzte aktive Katze bleibt."""
    con = db()
    try:
        aktive = con.execute("SELECT COUNT(*) FROM katze WHERE aktiv = 1").fetchone()[0]
        katze_id = request.form.get("id", type=int)
        if aktive > 1:
            with con:
                con.execute("UPDATE katze SET aktiv = 0 WHERE id = ?", (katze_id,))
    finally:
        con.close()
    antwort = redirect(url_for("katze", entfernt=1 if aktive > 1 else 0))
    antwort.delete_cookie(KATZE_COOKIE, path=(request.script_root or "") + "/")
    return antwort


@app.post("/katze_neu")
def katze_neu():
    name = (request.form.get("name") or "").strip()
    if not name or len(name) > 40:
        return redirect(url_for("katze", fehler_neu=1))
    con = db()
    try:
        doppelt = con.execute("SELECT 1 FROM katze WHERE aktiv = 1 AND lower(name) = lower(?)", (name,)).fetchone()
    finally:
        con.close()
    if doppelt:
        return redirect(url_for("katze", fehler_neu=2))
    con = db()
    try:
        with con:
            cur = con.execute(
                "INSERT INTO katze (name, kastriert, freigang, aktivitaetsfaktor, erstellt) VALUES (?, 1, 0, 1.2, ?)",
                (name, datenbank.jetzt_utc()))
        neue_id = cur.lastrowid
    finally:
        con.close()
    return katze_merken(redirect(url_for("katze", gespeichert=1)), neue_id)


tagesbedarf = heute_modul.tagesbedarf


def rechner(katze, kcal_100g=None, packung_g=None, kcal_snacks=0.0):
    """Werte für die Rechner-Karte; fehlende Angaben werden als Hinweis statt Zahl geliefert."""
    if katze["gewicht_aktuell"] is None:
        return {"hinweis": "Aktuelles Gewicht eintragen, dann rechnet der Rechner."}
    try:
        bedarf = fachlogik.tagesbedarf_kcal(
            katze["gewicht_aktuell"], katze["aktivitaetsfaktor"], katze["zielgewicht"]
        )
    except ValueError as exc:
        return {"hinweis": str(exc)}
    ergebnis = {
        "rer": fachlogik.rer(katze["gewicht_aktuell"]),
        "mer": bedarf,
        "snack_max": bedarf * fachlogik.SNACK_ANTEIL_MAX,
        "wasser": fachlogik.wasserrichtwert_ml(katze["gewicht_aktuell"]),
    }
    ergebnis["kcal_snacks"] = kcal_snacks
    if kcal_100g:
        ergebnis["menge_g"] = fachlogik.tagesmenge_g(bedarf, kcal_snacks, kcal_100g)
        if packung_g:
            ergebnis["packungen"] = ergebnis["menge_g"] / packung_g
    return ergebnis


FAKTOR_AUSWAHL = [
    (fachlogik.FAKTOREN["wohnung_kastriert"], "Wohnung, kastriert"),
    (fachlogik.FAKTOREN["freigang_kastriert"], "Freigang, kastriert"),
    (fachlogik.FAKTOREN["reduktion"], "Reduktion (nur auf Zielgewicht)"),
    (1.5, "Zunahme"),
]


def katze_speichern(con, katze, form):
    """Prüft und speichert das Profil. Gibt eine Fehlermeldung oder None zurück."""
    try:
        gewicht = zahl(form.get("gewicht_aktuell"))
        ziel = zahl(form.get("zielgewicht"))
        bcs = zahl(form.get("bcs"))
        faktor = zahl(form.get("aktivitaetsfaktor"))
        geburtsjahr = zahl(form.get("geburtsjahr"))
    except ValueError:
        return "Bitte Zahlen eingeben, z. B. 4,2."
    for wert, name in ((gewicht, "Gewicht"), (ziel, "Zielgewicht")):
        if wert is not None and not 1 <= wert <= 15:
            return f"{name} bitte in kg zwischen 1 und 15 angeben."
    if bcs is not None and (bcs != int(bcs) or not 1 <= bcs <= 9):
        return "BCS bitte als ganze Zahl von 1 bis 9 angeben."
    if faktor is None or not 0.5 <= faktor <= 2.0:
        return "Aktivitätsfaktor bitte zwischen 0,5 und 2,0 wählen."
    if geburtsjahr is not None and not 1990 <= geburtsjahr <= zeit.jetzt().year:
        return "Geburtsjahr bitte vierstellig angeben, z. B. 2023."
    try:
        gewicht_vorher = zahl(form.get("gewicht_vorher"))
    except ValueError:
        gewicht_vorher = None
    name = (form.get("name") or "").strip()
    if not name:
        return "Name fehlt."
    sensoren = {}
    for feld in ("petkit_besuch_entity", "petkit_gewicht_entity"):
        wert = (form.get(feld) or "").strip()
        if wert and not re.fullmatch(r"sensor\.[a-z0-9_]+", wert):
            return "PetKit-Sensor bitte als Entitäts-ID angeben, z. B. sensor.luna_gewicht."
        sensoren[feld] = wert or None
    # Nur eine im Formular geänderte Zahl gilt als neue Wiegung; sonst bleibt ein inzwischen
    # gemessenes (z. B. PetKit-)Gewicht erhalten
    geaendert = gewicht is not None and (form.get("gewicht_vorher") is None or gewicht != gewicht_vorher)
    if not geaendert:
        gewicht = katze["gewicht_aktuell"]
    with con:
        if (sensoren["petkit_besuch_entity"], sensoren["petkit_gewicht_entity"]) != (
                katze["petkit_besuch_entity"], katze["petkit_gewicht_entity"]):
            # neue Sensoren: Abgleich beginnt mit den letzten 7 Tagen
            con.execute("UPDATE katze SET petkit_besuch_entity = ?, petkit_gewicht_entity = ?, petkit_abgleich = NULL "
                        "WHERE id = ?", (sensoren["petkit_besuch_entity"], sensoren["petkit_gewicht_entity"], katze["id"]))
        con.execute(
            "UPDATE katze SET name = ?, geburtsjahr = ?, kastriert = ?, freigang = ?, gewicht_aktuell = ?, "
            "zielgewicht = ?, bcs = ?, aktivitaetsfaktor = ? WHERE id = ?",
            (
                name,
                int(geburtsjahr) if geburtsjahr else None,
                1 if form.get("kastriert") else 0,
                1 if form.get("freigang") else 0,
                gewicht,
                ziel,
                int(bcs) if bcs is not None else None,
                faktor,
                katze["id"],
            ),
        )
        # Jede Gewichtsänderung landet in der Historie (Grundlage für den Trend)
        if geaendert and gewicht != katze["gewicht_aktuell"]:
            con.execute(
                "INSERT INTO gewicht (katze_id, zeit, kg, quelle) VALUES (?, ?, ?, 'manuell')",
                (katze["id"], datenbank.jetzt_utc(), gewicht),
            )
    return None


@app.get("/")
def heute():
    con = db()
    try:
        tier = aktive_katze(con)
        einst = einstellungen.laden(con)
        h = heute_modul.zusammenfassung(con, tier, einst, tagesbedarf(tier))
    finally:
        con.close()
    return render_template("heute.html", tab="heute", titel="Heute", katze=tier, h=h, zeige_katzenwahl=True,
                           bezeichnung=produkte.bezeichnung, typ_text=gesundheit.TYP_TEXT)


@app.template_filter("datum")
def format_datum(text):
    return zeit.lokal(text).strftime("%d.%m.") if text else "–"


@app.template_filter("uhrzeit")
def format_uhrzeit(text):
    return zeit.lokal(text).strftime("%H:%M") if text else "–"


def fuetterung_pruefen(form, auswahl):
    """Rückgabe: (produkt, menge_g, zeitpunkt, fehler)."""
    produkt = next((p for p in auswahl if p["id"] == form.get("produkt_id", type=int)), None)
    if produkt is None:
        return None, None, None, "Bitte ein Futter wählen."
    try:
        menge = zahl(form.get("menge_g"))
    except ValueError:
        return produkt, None, None, "Menge bitte in g angeben, z. B. 42,5."
    if menge is None or not 0 < menge <= 2000:
        return produkt, None, None, "Menge bitte in g zwischen 1 und 2000 angeben."
    zeitpunkt, fehler = uhrzeit_lesen(form.get("uhrzeit"))
    return produkt, menge, zeitpunkt, fehler


def uhrzeit_lesen(text):
    """Optionale Uhrzeit „HH:MM“ der letzten 24 Stunden; leer = jetzt. Rückgabe: (zeitpunkt, fehler)."""
    text = (text or "").strip()
    if not text:
        return zeit.jetzt(), None
    try:
        zeitpunkt = zeit.heute_um(text)
    except ValueError:
        return None, "Uhrzeit bitte als HH:MM angeben."
    if zeitpunkt > zeit.jetzt() + datetime.timedelta(minutes=5):
        # nach Mitternacht nachgetragen (z. B. 23:30 um 0:10): gemeint ist gestern
        zeitpunkt -= datetime.timedelta(days=1)
    return zeitpunkt, None


@app.route("/fuettern", methods=["GET", "POST"])
def fuettern():
    con = db()
    try:
        tier = aktive_katze(con)
        auswahl = mahlzeiten.produkte_zum_fuettern(con)
        personen, vorbelegt = einstellungen.auswahl(einstellungen.laden(con), ha_benutzer())
        fehler, hinweise = None, []
        if request.method == "POST":
            produkt, menge, zeitpunkt, fehler = fuetterung_pruefen(request.form, auswahl)
            if not fehler:
                person = (request.form.get("person") or "").strip() or ha_user()
                mahlzeit_id, hinweise = mahlzeiten.fuettern(con, tier["id"], produkt, menge, zeitpunkt, person, ha_user())
                return redirect(url_for("fuettern", gespeichert=mahlzeit_id, hinweis=hinweise))
        gewaehlt_id = request.values.get("produkt_id", type=int)
        oben, weitere = mahlzeiten.auswahl_aufteilen(auswahl)
        gespeichert = None
        if request.args.get("gespeichert", type=int):
            gespeichert = con.execute(
                "SELECT m.*, p.marke, p.linie, p.sorte FROM mahlzeit m JOIN produkt p ON p.id = m.produkt_id "
                "WHERE m.id = ?", (request.args.get("gespeichert", type=int),)).fetchone()
        return render_template(
            "fuettern.html", tab="fuettern", titel="Füttern", katze=tier, auswahl=auswahl, zeige_katzenwahl=True,
            oben=oben, weitere=weitere,
            gewaehlt_id=gewaehlt_id or (oben[0]["id"] if oben else None),
            form=request.form if fehler else None, fehler=fehler,
            gespeichert=gespeichert, hinweise=request.args.getlist("hinweis"),
            rueckgaengig=mahlzeiten.rueckgaengig_moeglich(con, gespeichert) if gespeichert else False,
            zurueckgenommen=request.args.get("zurueckgenommen"), geloescht=request.args.get("geloescht"),
            offene=mahlzeiten.offene(con, tier["id"]), stufen=mahlzeiten.STUFEN_TEXT,
            rest_erfasst=mahlzeiten.laden(con, request.args.get("rest", type=int)) if request.args.get("rest") else None,
            heute=mahlzeiten.heute(con, tier["id"]), bezeichnung=produkte.bezeichnung, user=ha_user(),
            personen=personen, vorbelegt=vorbelegt,
        ), (400 if fehler else 200)
    finally:
        con.close()


@app.route("/rest", methods=["GET", "POST"])
def rest():
    """Rest einer Mahlzeit erfassen oder korrigieren (Schätzstufe, gewogen, verweigert)."""
    con = db()
    try:
        mahlzeit_id = request.values.get("id", type=int)
        mahlzeit = mahlzeiten.laden(con, mahlzeit_id) if mahlzeit_id else None
        if mahlzeit is None:
            abort(404)
        fehler = None
        if request.method == "POST":
            try:
                gewogen = zahl(request.form.get("rest_g"))
            except ValueError:
                gewogen, fehler = None, "Rest bitte in g angeben, z. B. 12,5."
            if not fehler:
                fehler = mahlzeiten.rest_erfassen(
                    con, mahlzeit_id, stufe=request.form.get("stufe"), rest_gewogen=gewogen,
                    verweigert=bool(request.form.get("verweigert")),
                )
            if not fehler:
                mitteilung_entfernen(mahlzeit_id)
                return redirect(url_for("fuettern", rest=mahlzeit_id))
        return render_template(
            "rest.html", tab="fuettern", titel="Rest", m=mahlzeit, fehler=fehler,
            katze_name=con.execute("SELECT name FROM katze WHERE id = ?", (mahlzeit["katze_id"],)).fetchone()[0],
            stufen=mahlzeiten.STUFEN_TEXT, bezeichnung=produkte.bezeichnung,
        ), (400 if fehler else 200)
    finally:
        con.close()


@app.route("/snack", methods=["GET", "POST"])
def snack():
    con = db()
    try:
        tier = aktive_katze(con)
        einst = einstellungen.laden(con)
        auswahl = snacks.snack_produkte(con)
        personen, vorbelegt = einstellungen.auswahl(einst, ha_benutzer())
        fehler = None
        if request.method == "POST":
            produkt = next((p for p in auswahl if p["id"] == request.form.get("produkt_id", type=int)), None)
            try:
                stueck = zahl(request.form.get("stueck"))
                menge = zahl(request.form.get("menge_g"))
            except ValueError:
                stueck = menge = None
                fehler = "Bitte Zahlen eingeben."
            if not fehler and produkt is None:
                fehler = "Bitte einen Snack wählen."
            elif not fehler and (stueck is None or not 0 < stueck <= 50):
                fehler = "Anzahl bitte zwischen 1 und 50 angeben."
            elif not fehler and menge is not None and not 0 < menge <= 500:
                fehler = "Menge bitte in g zwischen 1 und 500 angeben."
            if not fehler:
                person = (request.form.get("person") or "").strip() or ha_user()
                snack_id = snacks.erfassen(con, tier["id"], produkt, stueck, menge, person, ha_user())
                return redirect(url_for("snack", gespeichert=snack_id))
        stand = snacks.tagesstand(con, tier["id"], einst, tagesbedarf(tier))
        gespeichert_id = request.args.get("gespeichert", type=int)
        return render_template(
            "snack.html", tab="fuettern", titel="Snack", auswahl=auswahl, stand=stand, katze=tier, zeige_katzenwahl=True, seite="snack",
            personen=personen, vorbelegt=vorbelegt, fehler=fehler, form=request.form if fehler else None,
            gespeichert=next((x for x in stand["liste"] if x["id"] == gespeichert_id), None),
            zurueckgenommen=request.args.get("zurueckgenommen"),
            ist_kind=lambda name: einstellungen.ist_kind(einst, name),
        ), (400 if fehler else 200)
    finally:
        con.close()


@app.post("/snack_rueckgaengig")
def snack_rueckgaengig():
    con = db()
    try:
        ok = snacks.rueckgaengig(con, request.form.get("snack_id", type=int))
    finally:
        con.close()
    return redirect(url_for("snack", zurueckgenommen=1 if ok else 0))


@app.route("/einstellungen", methods=["GET", "POST"])
def einstellungen_seite():
    con = db()
    try:
        einst = einstellungen.laden(con)
        darf = einstellungen.darf_aendern(einst, ha_benutzer())
        fehler = None
        if request.method == "POST":
            if not darf:
                abort(403)
            personen, limit, fehler = einstellungen.aus_formular(request.form)
            abweichungen = None
            if not fehler:
                abweichungen, fehler = schwellen.aus_formular(request.form)
            if not fehler and personen and not einstellungen.darf_aendern(
                    {"personen": personen, "snack_limit_kinder": limit}, ha_benutzer()):
                fehler = "Du würdest dich selbst aussperren: Trage deinen HA-Benutzer bei einer erwachsenen Person ein."
            if not fehler:
                einstellungen.speichern(con, personen, limit)
                schwellen.speichern(con, abweichungen)
                return redirect(url_for("einstellungen_seite", gespeichert=1))
        return render_template(
            "einstellungen.html", tab="katze", titel="Einstellungen", einst=einst, darf=darf,
            rollen=einstellungen.ROLLEN, fehler=fehler, user=ha_user(),
            benutzername=request.headers.get("X-Remote-User-Name") or "",
            zugeordnet=einstellungen.person_zu_benutzer(einst, ha_benutzer()),
            definitionen=schwellen.DEFINITIONEN, abweichungen=schwellen.abweichungen(con),
            form=request.form if fehler else None,
            gespeichert=request.args.get("gespeichert") and not fehler,
        ), (400 if fehler else 200)
    finally:
        con.close()


@app.route("/gesundheit", methods=["GET", "POST"])
def gesundheit_seite():
    con = db()
    try:
        tier = aktive_katze(con)
        personen, vorbelegt = einstellungen.auswahl(einstellungen.laden(con), ha_benutzer())
        fehler = None
        if request.method == "POST":
            typ = request.form.get("typ")
            zeitpunkt, fehler = uhrzeit_lesen(request.form.get("uhrzeit"))
            if not fehler and typ not in gesundheit.TYP_TEXT:
                fehler = "Bitte auswählen, was passiert ist."
            foto = None
            if not fehler:
                try:
                    foto = gesundheit.foto_speichern(request.files.get("foto"), FOTO_ORDNER)
                except ValueError as exc:
                    fehler = str(exc)
            if not fehler:
                ereignis_id = gesundheit.erfassen(
                    con, tier["id"], typ, zeitpunkt,
                    person=(request.form.get("person") or "").strip() or ha_user(), erfasst_von=ha_user(),
                    blut=bool(request.form.get("blut")), apathie=bool(request.form.get("apathie")),
                    notiz=(request.form.get("notiz") or "").strip() or None, foto=foto,
                )
                return redirect(url_for("gesundheit_seite", gespeichert=ereignis_id))
        ereignisse = gesundheit.liste(con, tier["id"])
        return render_template(
            "gesundheit.html", tab="fuettern", titel="Gesundheit", typen=gesundheit.TYPEN, zeige_katzenwahl=True, seite="gesundheit",
            typ_text=gesundheit.TYP_TEXT, ereignisse=ereignisse, hinweise=gesundheit.hinweise(con, tier["id"]),
            personen=personen, vorbelegt=vorbelegt, fehler=fehler, form=request.form if fehler else None,
            gespeichert=request.args.get("gespeichert", type=int), geloescht=request.args.get("geloescht"),
            loeschbar=gesundheit.loeschen_moeglich, katze=tier,
        ), (400 if fehler else 200)
    finally:
        con.close()


@app.post("/ereignis_loeschen")
def ereignis_loeschen():
    con = db()
    try:
        ok = gesundheit.loeschen(con, request.form.get("ereignis_id", type=int), FOTO_ORDNER)
    finally:
        con.close()
    return redirect(url_for("gesundheit_seite", geloescht=1 if ok else 0))


@app.get("/foto")
def foto():
    name = request.args.get("datei", "")
    # nur selbst vergebene Namen (32 Hex-Zeichen + Endung), kein Pfad
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|heic|webp)", name):
        abort(404)
    return send_from_directory(FOTO_ORDNER, name)


@app.post("/mahlzeit_loeschen")
def mahlzeit_loeschen():
    con = db()
    try:
        mahlzeit_id = request.form.get("id", type=int)
        ergebnis = mahlzeiten.loeschen(con, mahlzeit_id)
    finally:
        con.close()
    if ergebnis is None:
        abort(404)
    mitteilung_entfernen(mahlzeit_id)
    return redirect(url_for("fuettern", geloescht=ergebnis))


@app.post("/wiegung_umschalten")
def wiegung_umschalten():
    con = db()
    try:
        tier = aktive_katze(con)
        verlauf_modul.wiegung_umschalten(con, tier["id"], request.form.get("id", type=int))
    finally:
        con.close()
    return redirect(url_for("verlauf", tage=request.form.get("tage", type=int) or 30))


@app.post("/rueckgaengig")
def rueckgaengig():
    con = db()
    try:
        mahlzeit_id = request.form.get("mahlzeit_id", type=int)
        ok = mahlzeiten.rueckgaengig(con, mahlzeit_id)
    finally:
        con.close()
    if ok:
        mitteilung_entfernen(mahlzeit_id)
    return redirect(url_for("fuettern", zurueckgenommen=1 if ok else 0))


@app.get("/futter")
def futter():
    con = db()
    try:
        tier = aktive_katze(con)
        liste = [(p, produkte.trockenmasse(p)) for p in produkte.liste(con)]
        vorlieben, einbruch = praeferenz.aktualisieren(con, tier["id"])
        s_werte = schwellen.laden(con)
    finally:
        con.close()
    attribute = sorted(((bezug, s, e) for (bezug, s), e in vorlieben.items() if bezug != "produkt"),
                       key=lambda x: (list(praeferenz.BEZUG_TEXT).index(x[0]), -(x[2]["score"] or -9)))
    return render_template(
        "futter.html", tab="futter", titel="Futter", liste=liste, katze=tier, zeige_katzenwahl=True,
        bezeichnung=produkte.bezeichnung, gespeichert=request.args.get("gespeichert"),
        vorlieben=vorlieben, attribute=attribute, einbruch=einbruch, s=s_werte,
        status_text=praeferenz.STATUS_TEXT, bezug_text=praeferenz.BEZUG_TEXT,
        gesperrt=request.args.get("gesperrt"), neu_berechnet=request.args.get("neu_berechnet", type=int),
    )


@app.get("/ean_daten")
def ean_daten_abfragen():
    """Produktdaten zur EAN aus Open Pet Food Facts; nur Vorschläge, abschaltbar über die Option."""
    if options().get("online_produktdaten") is False:
        return jsonify(ok=False, fehler="Online-Abfrage ist in der Add-on-Konfiguration ausgeschaltet."), 403
    ean = produkte.ean_normalisieren(request.args.get("ean"))
    if not produkte.ean_gueltig(ean):
        return jsonify(ok=False, fehler="Keine gültige EAN."), 400
    quelle, werte = ean_daten.abfragen(ean)
    if not werte:
        return jsonify(ok=True, quelle=None, werte={})
    return jsonify(ok=True, quelle=quelle, werte=werte)


@app.post("/text_auswerten")
def text_auswerten():
    """Eingefügten Text (z. B. Live Text vom iPhone) wie die Texterkennung auswerten; nur Vorschläge."""
    text = (request.form.get("text") or (request.get_json(silent=True) or {}).get("text") or "")[:20000]
    if not text.strip():
        return jsonify(ok=False, fehler="Kein Text eingefügt."), 400
    werte, zweifel = texterkennung.analysieren(text)
    return jsonify(ok=True, werte=werte, zweifel=zweifel, text=text[:4000])


@app.get("/kosten")
def kosten():
    con = db()
    try:
        tier = aktive_katze(con)
        tage = request.args.get("tage", type=int)
        tage = tage if tage in kosten_modul.TAGE_AUSWAHL else 30
        k = kosten_modul.auswerten(con, tier["id"], tage)
        vergleich = kosten_modul.preisvergleich(con)
    finally:
        con.close()
    return render_template("kosten.html", tab="futter", titel="Kosten", k=k, vergleich=vergleich, zeige_katzenwahl=True, katze=tier, seite="kosten",
                           auswahl=kosten_modul.TAGE_AUSWAHL, bezeichnung=produkte.bezeichnung)


@app.post("/sperren")
def sperren():
    """Sorte sperren – nur auf ausdrückliche Entscheidung, nie automatisch."""
    produkt_id = request.form.get("id", type=int)
    con = db()
    try:
        with con:
            con.execute("UPDATE produkt SET status = 'gesperrt', geaendert = ? WHERE id = ? AND status = 'aktiv'",
                        (datenbank.jetzt_utc(), produkt_id))
    finally:
        con.close()
    return redirect(url_for("futter", gesperrt=produkt_id))


@app.route("/produkt", methods=["GET", "POST"])
def produkt():
    """Futter anlegen (ohne id) oder bearbeiten (?id=…). Flache URL, damit relative Links stimmen."""
    con = db()
    try:
        produkt_id = request.values.get("id", type=int)
        vorhanden = produkte.laden(con, produkt_id) if produkt_id else None
        if produkt_id and vorhanden is None:
            abort(404)
        fehler = None
        if request.method == "POST":
            daten, bestand, fehler = produkte.aus_formular(request.form)
            if not fehler:
                produkt_id, fehler = produkte.speichern(con, daten, bestand, produkt_id)
            if not fehler:
                neu = produkte.neu_berechnen(con, produkt_id, vorhanden) if vorhanden else 0
                return redirect(url_for("futter", gespeichert=produkt_id, neu_berechnet=neu or None))
        # Vorlage nur beim Anlegen: übernimmt Werte einer vorhandenen Sorte (ohne Sorte, EAN, Bestand, Status)
        vorlage_id = request.args.get("vorlage", type=int)
        vorlage = produkte.laden(con, vorlage_id) if vorlage_id and not vorhanden else None
        return render_template(
            "produkt.html", tab="futter", titel=produkte.bezeichnung(vorhanden) if vorhanden else "Neues Futter",
            p=vorhanden, quelle=vorhanden or vorlage, vorlage=vorlage,
            vorlagen=produkte.liste(con) if not vorhanden else [], bezeichnung=produkte.bezeichnung,
            form=request.form if fehler else None, fehler=fehler,
            ean_vorbelegt=request.args.get("ean", ""),
            futterarten=produkte.FUTTERARTEN, status=produkte.STATUS, naehrstoffe=produkte.NAEHRSTOFFE,
            tm=produkte.trockenmasse(vorhanden) if vorhanden else None,
            vorliebe=praeferenz.aktualisieren(con, aktive_katze(con)["id"])[0].get(("produkt", str(vorhanden["id"])))
            if vorhanden else None,
            status_text=praeferenz.STATUS_TEXT, liebling_n=schwellen.laden(con)["liebling_n"],
            katze=aktive_katze(con),
        ), (400 if fehler else 200)
    finally:
        con.close()


@app.get("/scan")
def scan():
    """Barcode-Erfassung: Kamera und Foto dekodieren im Browser (ZXing), Ergebnis kommt als ?ean=…"""
    ean = produkte.ean_normalisieren(request.args.get("ean"))
    ziel = "fuettern" if request.args.get("ziel") == "fuettern" else "futter"
    fehler = None
    if ean:
        if not produkte.ean_gueltig(ean):
            fehler = f"„{ean}“ ist keine gültige EAN. Bitte erneut scannen oder die Ziffern prüfen."
        else:
            con = db()
            try:
                treffer = produkte.suchen_ean(con, ean)
            finally:
                con.close()
            if treffer and ziel == "fuettern":
                return redirect(url_for("fuettern", produkt_id=treffer["id"]))
            if treffer:
                return redirect(url_for("produkt", id=treffer["id"]))
            return redirect(url_for("produkt", ean=ean))
    return render_template(
        "scan.html", tab="fuettern" if ziel == "fuettern" else "futter", titel="Barcode",
        fehler=fehler, ean=ean, ziel=ziel,
    ), (400 if fehler else 200)


@app.route("/verlauf", methods=["GET", "POST"])
def verlauf():
    con = db()
    try:
        tier = aktive_katze(con)
        tage = request.values.get("tage", type=int)
        tage = tage if tage in verlauf_modul.TAGE_AUSWAHL else 30
        fehler = None
        if request.method == "POST":
            try:
                kg = zahl(request.form.get("kg"))
                tag = datetime.date.fromisoformat(request.form.get("datum") or verlauf_modul.heute_lokal().isoformat())
            except ValueError:
                kg, tag, fehler = None, None, "Bitte Gewicht in kg (z. B. 4,2) und ein gültiges Datum angeben."
            if not fehler and (kg is None or not 1 <= kg <= 15):
                fehler = "Gewicht bitte in kg zwischen 1 und 15 angeben."
            elif not fehler and tag > verlauf_modul.heute_lokal():
                fehler = "Das Datum liegt in der Zukunft."
            if not fehler:
                verlauf_modul.gewicht_eintragen(con, tier, kg, tag)
                return redirect(url_for("verlauf", tage=tage, gespeichert=1))
        gewicht = verlauf_modul.gewicht_daten(con, tier["id"], tage)
        kcal = verlauf_modul.kcal_tage(con, tier["id"], tage)
        mer = tagesbedarf(tier)
        ereignisse = [e for e in gesundheit.liste(con, tier["id"], tage=tage)]
        return render_template(
            "verlauf.html", tab="verlauf", titel="Verlauf", katze=tier, tage=tage, zeige_katzenwahl=True,
            auswahl=verlauf_modul.TAGE_AUSWAHL, gewicht=gewicht,
            g_diagramm=verlauf_modul.gewicht_diagramm(gewicht, tage),
            kcal=kcal, k_diagramm=verlauf_modul.kcal_diagramm(kcal, tage, mer), mer=mer,
            ereignisse=ereignisse, typ_text=gesundheit.TYP_TEXT, fehler=fehler,
            gespeichert=request.args.get("gespeichert"), heute=verlauf_modul.heute_lokal().isoformat(),
            wiegungen=verlauf_modul.wiegungen_letzte(con, tier["id"]),
        ), (400 if fehler else 200)
    finally:
        con.close()


@app.route("/katze", methods=["GET", "POST"])
def katze():
    con = db()
    try:
        tier = aktive_katze(con)
        fehler = None
        if request.method == "POST":
            fehler = katze_speichern(con, tier, request.form)
            if not fehler:
                return redirect(url_for("katze", gespeichert=1))
        auswahl = con.execute(
            "SELECT * FROM produkt WHERE status = 'aktiv' AND futterart = 'allein' AND kcal_100g IS NOT NULL "
            "ORDER BY marke, linie, sorte"
        ).fetchall()
        gewaehlt = next((p for p in auswahl if p["id"] == request.args.get("produkt_id", type=int)), None)
        try:
            kcal_100g = zahl(request.args.get("kcal_100g"))
            packung_g = zahl(request.args.get("packung_g")) or 85
        except ValueError:
            kcal_100g, packung_g = None, 85
        if gewaehlt:
            kcal_100g, packung_g = gewaehlt["kcal_100g"], gewaehlt["packung_g"]
        letzte = con.execute(
            "SELECT zeit, kg FROM gewicht WHERE katze_id = ? AND verworfen = 0 ORDER BY zeit DESC LIMIT 1",
            (tier["id"],),
        ).fetchone()
        return render_template(
            "katze.html",
            tab="katze",
            titel=tier["name"],
            katze=tier,
            fehler=fehler,
            form=request.form if fehler else None,
            gespeichert=request.args.get("gespeichert") and not fehler,
            r=rechner(tier, kcal_100g, packung_g, sum(x["kcal"] or 0 for x in snacks.heute(con, tier["id"]))),
            kcal_100g=kcal_100g,
            packung_g=packung_g,
            auswahl=auswahl,
            gewaehlt=gewaehlt,
            bezeichnung=produkte.bezeichnung,
            faktoren=FAKTOR_AUSWAHL,
            letzte_wiegung=letzte,
            user=ha_user(),
            fehler_neu=request.args.get("fehler_neu", type=int), entfernt=request.args.get("entfernt"),
            katzen=con.execute("SELECT id, name FROM katze WHERE aktiv = 1 ORDER BY id").fetchall(),
            zeige_katzenwahl=True,
            petkit_vorschlaege=petkit.vorschlaege(SUPERVISOR_TOKEN, tier["name"]) if not DEV_MODE else ([], []),
            petkit_stand={"gaenge_24h": petkit.toilettengaenge(con, tier["id"], 1),
                          "wiegungen_7t": con.execute("SELECT COUNT(*) FROM gewicht WHERE katze_id = ? AND quelle = 'petkit' "
                                                      "AND zeit >= ?", (tier["id"], zeit.iso(zeit.jetzt() - datetime.timedelta(days=7)))).fetchone()[0]},
        ), (400 if fehler else 200)
    finally:
        con.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099, debug=DEV_MODE)
