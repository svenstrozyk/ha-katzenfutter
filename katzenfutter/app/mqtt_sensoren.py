"""Sensoren nach Home Assistant per MQTT-Discovery.

Ein Hintergrund-Thread hält die Verbindung zum Broker, meldet die Geräte-Konfiguration (retained)
und sendet den Zustand nach jeder Änderung sowie jede Minute. Zugangsdaten kommen vom Supervisor
(services: mqtt:need), ersatzweise aus den Add-on-Optionen.
"""
import json
import logging
import re
import threading
import time

import requests

import datenbank
import einstellungen
import heute
import kosten
import produkte

log = logging.getLogger("katzenfutter.mqtt")

PRAEFIX = "homeassistant"
STATUS_TOPIC = "katzenfutter/status"
INTERVALL_SEKUNDEN = 60

# (Komponente, Schlüssel, Name, Einheit, device_class, state_class, Symbol)
SENSOREN = [
    ("sensor", "kcal_heute", "kcal heute", "kcal", None, "measurement", "mdi:fire"),
    ("sensor", "kcal_verbleibend", "kcal verbleibend", "kcal", None, "measurement", "mdi:food-drumstick-outline"),
    ("sensor", "tagesbedarf", "Tagesbedarf", "kcal", None, "measurement", "mdi:target"),
    ("sensor", "futter_gefressen_heute", "Futter gefressen heute", "g", "weight", "measurement", "mdi:bowl-mix"),
    ("sensor", "snacks_heute", "Snacks heute", "kcal", None, "measurement", "mdi:cookie"),
    ("sensor", "letzte_mahlzeit", "Letzte Mahlzeit", None, "timestamp", None, "mdi:clock-outline"),
    ("sensor", "offene_reste", "Offene Reste", None, None, "measurement", "mdi:help-circle-outline"),
    ("sensor", "gewicht", "Gewicht", "kg", "weight", "measurement", "mdi:scale-bathroom"),
    ("sensor", "wasser_aus_futter_heute", "Wasser aus Futter heute", "mL", "volume", "measurement", "mdi:water"),
    ("sensor", "bestand_packungen", "Bestand Packungen", None, None, "measurement", "mdi:package-variant"),
    ("sensor", "futterkosten_30_tage", "Futterkosten 30 Tage", "EUR", "monetary", "total", "mdi:currency-eur"),
    ("binary_sensor", "keine_futteraufnahme", "Keine Futteraufnahme 24 h", None, "problem", None, None),
    ("binary_sensor", "tierarzt_hinweis", "Tierarzt-Hinweis", None, "problem", None, None),
    ("binary_sensor", "snack_limit_erreicht", "Snack-Limit Kinder erreicht", None, None, None, "mdi:cookie-alert"),
]
ATTRIBUTE = {"tierarzt_hinweis": "hinweise", "bestand_packungen": "bestand"}


def slug(text):
    ersetzt = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "_", ersetzt).strip("_") or "katze"


def zustand_topic(katze):
    return f"katzenfutter/{katze['id']}/zustand"


def discovery(katze):
    """Liste von (Topic, Payload) für alle Entitäten einer Katze."""
    kennung = f"katzenfutter_{katze['id']}"
    geraet = {"identifiers": [kennung], "name": f"Katzenfutter {katze['name']}",
              "manufacturer": "ha-katzenfutter", "model": "Home-Assistant-Add-on"}
    ergebnis = []
    for komponente, schluessel, name, einheit, klasse, state_class, symbol in SENSOREN:
        konfig = {
            "name": name,
            "unique_id": f"{kennung}_{schluessel}",
            "default_entity_id": f"{komponente}.{slug(katze['name'])}_{schluessel}",
            "state_topic": zustand_topic(katze),
            "availability_topic": STATUS_TOPIC,
            "device": geraet,
            "has_entity_name": True,
        }
        if komponente == "binary_sensor":
            konfig["value_template"] = "{{ 'ON' if value_json.%s else 'OFF' }}" % schluessel
        else:
            konfig["value_template"] = "{{ value_json.%s }}" % schluessel
        for feld, wert in (("unit_of_measurement", einheit), ("device_class", klasse),
                           ("state_class", state_class), ("icon", symbol)):
            if wert:
                konfig[feld] = wert
        if schluessel in ATTRIBUTE:
            konfig["json_attributes_topic"] = zustand_topic(katze)
            konfig["json_attributes_template"] = "{{ value_json.%s | tojson }}" % ATTRIBUTE[schluessel]
        ergebnis.append((f"{PRAEFIX}/{komponente}/{kennung}/{schluessel}/config", konfig))
    return ergebnis


def _runden(wert, stellen=0):
    return None if wert is None else round(wert, stellen) if stellen else round(wert)


def zustand(con, katze):
    """Zustand einer Katze als JSON-fähiges Dict (unbekannte Werte als None)."""
    einst = einstellungen.laden(con)
    mer = heute.tagesbedarf(katze)
    h = heute.zusammenfassung(con, katze, einst, mer)
    letzte = con.execute("SELECT MAX(zeit) FROM mahlzeit WHERE katze_id = ?", (katze["id"],)).fetchone()[0]
    bestand = {produkte.bezeichnung(p): {"packungen": p["packungen"] or 0, "angebrochen_g": p["angebrochen_g"] or 0}
               for p in produkte.liste(con) if p["status"] == "aktiv" and p["futterart"] != "snack"}
    tierarzt = [text for stufe, text in h["gesundheit"] if stufe == "tierarzt"]
    if h["keine_aufnahme"]:
        tierarzt.insert(0, "Seit mehr als 24 Stunden keine Futteraufnahme erfasst.")
    return {
        "kcal_heute": _runden(h["gefressen_kcal"] + h["snack_kcal"]),
        "kcal_verbleibend": _runden(h.get("rest_kcal")),
        "tagesbedarf": _runden(mer),
        "futter_gefressen_heute": _runden(h["gefressen_g"], 1),
        "snacks_heute": _runden(h["snack_kcal"]),
        "letzte_mahlzeit": letzte,
        "offene_reste": h["offene_reste"],
        "gewicht": katze["gewicht_aktuell"],
        "wasser_aus_futter_heute": _runden(h["wasser"]["gesamt_ml"]) if h["wasser"] else None,
        "bestand_packungen": sum(b["packungen"] for b in bestand.values()),
        "futterkosten_30_tage": round(kosten.auswerten(con, katze["id"], 30)["gesamt"], 2),
        "bestand": bestand,
        "keine_futteraufnahme": h["keine_aufnahme"],
        "tierarzt_hinweis": bool(tierarzt),
        "hinweise": {"tierarzt": tierarzt,
                     "hinweise": [text for stufe, text in h["gesundheit"] if stufe == "hinweis"] + h["gewicht_hinweise"]
                     + (["Akzeptanz sinkt über alle Futter."] if h["akzeptanzeinbruch"] else [])},
        "snack_limit_erreicht": h["snack"]["limit_erreicht"],
    }


def zugangsdaten(token, optionen):
    """Broker-Zugang vom Supervisor, sonst aus den Optionen. None, wenn keiner bekannt ist."""
    if token:
        try:
            antwort = requests.get("http://supervisor/services/mqtt",
                                   headers={"Authorization": f"Bearer {token}"}, timeout=10)
            antwort.raise_for_status()
            daten = antwort.json().get("data") or {}
            if daten.get("host"):
                return {"host": daten["host"], "port": int(daten.get("port") or 1883),
                        "user": daten.get("username"), "password": daten.get("password")}
        except (requests.RequestException, ValueError) as exc:
            log.warning("MQTT-Zugang vom Supervisor nicht abrufbar: %s", exc)
    if optionen.get("mqtt_host"):
        return {"host": optionen["mqtt_host"], "port": int(optionen.get("mqtt_port") or 1883),
                "user": optionen.get("mqtt_user"), "password": optionen.get("mqtt_password")}
    return None


class Dienst:
    """Hintergrund-Thread für die MQTT-Verbindung."""

    def __init__(self, db_pfad, token, optionen_lesen):
        self.db_pfad = db_pfad
        self.token = token
        self.optionen_lesen = optionen_lesen
        self.ausloeser = threading.Event()
        self.discovery_noetig = True

    def start(self):
        threading.Thread(target=self._lauf, name="mqtt", daemon=True).start()

    def aenderung(self):
        self.ausloeser.set()

    def senden(self, client):
        con = datenbank.verbinden(self.db_pfad)
        try:
            katzen = con.execute("SELECT * FROM katze WHERE aktiv = 1").fetchall()
            if self.discovery_noetig:
                for katze in katzen:
                    for topic, konfig in discovery(katze):
                        client.publish(topic, json.dumps(konfig, ensure_ascii=False), qos=1, retain=True)
                client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
                self.discovery_noetig = False
            for katze in katzen:
                client.publish(zustand_topic(katze), json.dumps(zustand(con, katze), ensure_ascii=False),
                               qos=1, retain=True)
        finally:
            con.close()

    def _lauf(self):
        import paho.mqtt.client as mqtt

        while True:
            try:
                zugang = zugangsdaten(self.token, self.optionen_lesen())
                if zugang is None:
                    log.warning("Kein MQTT-Broker bekannt – Sensoren deaktiviert, neuer Versuch in 5 Minuten.")
                    time.sleep(300)
                    continue
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="katzenfutter-addon")
                if zugang["user"]:
                    client.username_pw_set(zugang["user"], zugang["password"])
                client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)

                def verbunden(_client, _daten, _flags, grund, _eigenschaften):
                    if not grund.is_failure:
                        # nach (Wieder-)Verbindung Konfiguration erneut melden, z. B. nach Broker-Neustart
                        self.discovery_noetig = True
                        self.ausloeser.set()
                        log.info("MQTT verbunden mit %s:%s", zugang["host"], zugang["port"])
                    else:
                        log.warning("MQTT-Verbindung abgelehnt: %s", grund)

                client.on_connect = verbunden
                client.connect(zugang["host"], zugang["port"], keepalive=60)
                client.loop_start()
                try:
                    while True:
                        self.ausloeser.wait(INTERVALL_SEKUNDEN)
                        self.ausloeser.clear()
                        if client.is_connected():
                            self.senden(client)
                finally:
                    client.loop_stop()
                    client.disconnect()
            except OSError as exc:
                # Broker nicht erreichbar, z. B. während eines Neustarts von Mosquitto
                log.warning("MQTT-Broker nicht erreichbar (%s), neuer Versuch in 30 Sekunden", exc)
                time.sleep(30)
            except Exception:  # Dienst darf nie die Oberfläche beeinträchtigen
                log.exception("MQTT-Dienst unterbrochen, neuer Versuch in 30 Sekunden")
                time.sleep(30)
