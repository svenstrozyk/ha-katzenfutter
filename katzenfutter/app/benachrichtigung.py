"""Rest-Erinnerung per Mitteilung mit Aktionen; Antworten kommen als Ereignis mobile_app_notification_action.

Zwei Hintergrund-Threads: einer prüft jede Minute auf fällige Erinnerungen, einer hört über die
HA-WebSocket-API auf Antworten. Eine Antwort trägt den Rest nur ein, wenn noch keiner erfasst ist.
"""
import datetime
import json
import logging
import threading
import time

import requests

import datenbank
import fachlogik
import mahlzeiten
import warnungen
import zeit

log = logging.getLogger("katzenfutter.mitteilung")

HA_API = "http://supervisor/core/api"
HA_WS = "ws://supervisor/core/websocket"
AKTION_PRAEFIX = "KATZENFUTTER_REST"
MAX_ALTER_STUNDEN = 12

AKTIONEN = [
    ("nichts", "Alles gefressen"),
    ("wenig", "Wenig übrig"),
    ("haelfte", "Hälfte übrig"),
    ("viel", "Viel übrig"),
    ("unberuehrt", "Unberührt"),
]


def empfaenger(optionen):
    """Mitteilungsdienste ohne „notify.“ aus notify_services (leer = automatisch, siehe Dienst.ziele)."""
    liste = optionen.get("notify_services") or []
    return [d.strip()[len("notify."):] if d.strip().startswith("notify.") else d.strip() for d in liste if d and d.strip()]


def erinnerung_minuten(optionen):
    wert = optionen.get("rest_erinnerung_minuten")
    return 30 if wert is None else int(wert)


def tag(mahlzeit_id):
    return f"katzenfutter-rest-{mahlzeit_id}"


def aktion_kennung(mahlzeit_id, stufe):
    return f"{AKTION_PRAEFIX}|{mahlzeit_id}|{stufe}"


def aktion_lesen(text):
    """(mahlzeit_id, stufe) aus einer Aktionskennung oder None."""
    teile = (text or "").split("|")
    if len(teile) != 3 or teile[0] != AKTION_PRAEFIX or not teile[1].isdigit() or teile[2] not in fachlogik.REST_STUFEN:
        return None
    return int(teile[1]), teile[2]


def nachricht(mahlzeit, katze_name, panel_pfad):
    """Payload für notify.<dienst>."""
    uhr = zeit.lokal(mahlzeit["zeit"]).strftime("%H:%M")
    menge = f"{mahlzeit['angeboten_g']:g}".replace(".", ",")
    daten = {
        "tag": tag(mahlzeit["id"]),
        "group": "katzenfutter",
        "url": panel_pfad,
        "actions": [{"action": aktion_kennung(mahlzeit["id"], stufe), "title": titel} for stufe, titel in AKTIONEN]
        + [{"action": "URI", "title": "Wiegen …", "uri": panel_pfad}],
    }
    return {
        "title": f"Hat {katze_name} aufgefressen?",
        "message": f"{menge} g {mahlzeit['sorte']} um {uhr} ({mahlzeit['person'] or 'unbekannt'}). Wie viel ist übrig?",
        "data": daten,
    }


def faellige(con, minuten):
    """Mahlzeiten ohne Rest und ohne Erinnerung, älter als `minuten`, aber höchstens 12 h alt."""
    jetzt = zeit.jetzt()
    return con.execute(
        "SELECT m.*, p.sorte, k.name AS katze_name FROM mahlzeit m JOIN produkt p ON p.id = m.produkt_id "
        "JOIN katze k ON k.id = m.katze_id "
        "WHERE m.rest_g IS NULL AND m.erinnert IS NULL AND m.zeit <= ? AND m.zeit >= ? ORDER BY m.zeit",
        (zeit.iso(jetzt - datetime.timedelta(minutes=minuten)),
         zeit.iso(jetzt - datetime.timedelta(hours=MAX_ALTER_STUNDEN))),
    ).fetchall()


def antwort_verarbeiten(con, aktion):
    """Trägt den Rest aus einer Mitteilungsaktion ein. Rückgabe: mahlzeit_id, wenn eingetragen."""
    gelesen = aktion_lesen(aktion)
    if gelesen is None:
        return None
    mahlzeit_id, stufe = gelesen
    mahlzeit = mahlzeiten.laden(con, mahlzeit_id)
    if mahlzeit is None or mahlzeit["rest_g"] is not None:
        # schon erfasst (z. B. von jemand anderem) – nicht überschreiben
        return None
    fehler = mahlzeiten.rest_erfassen(con, mahlzeit_id, stufe=stufe)
    return None if fehler else mahlzeit_id


class Dienst:
    def __init__(self, db_pfad, token, optionen_lesen, panel_pfad, bei_aenderung=None):
        self.db_pfad = db_pfad
        self.token = token
        self.optionen_lesen = optionen_lesen
        self.panel_pfad = panel_pfad
        self.bei_aenderung = bei_aenderung or (lambda: None)
        self._mobile = None

    def start(self):
        threading.Thread(target=self._erinnern, name="erinnerung", daemon=True).start()
        threading.Thread(target=self._zuhoeren, name="aktionen", daemon=True).start()

    # --- Senden ------------------------------------------------------------

    def mobile_geraete(self):
        """Alle notify.mobile_app_*-Dienste aus Home Assistant (eine Stunde zwischengespeichert)."""
        if self._mobile is None or time.monotonic() - self._mobile[0] > 3600:
            antwort = requests.get(f"{HA_API}/services", timeout=10, headers={"Authorization": f"Bearer {self.token}"})
            antwort.raise_for_status()
            dienste = next((d.get("services", {}) for d in antwort.json() if d.get("domain") == "notify"), {})
            self._mobile = (time.monotonic(), sorted(n for n in dienste if n.startswith("mobile_app_")))
        return self._mobile[1]

    def ziele(self, optionen):
        """Eingetragene Empfänger; ohne Eintrag alle Handys mit Home-Assistant-App."""
        liste = empfaenger(optionen)
        if liste:
            return liste
        try:
            return self.mobile_geraete()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Mobile Geräte nicht ermittelt: %s", exc)
            return []

    def _senden(self, dienst, payload):
        antwort = requests.post(f"{HA_API}/services/notify/{dienst}", json=payload, timeout=10,
                                headers={"Authorization": f"Bearer {self.token}"})
        antwort.raise_for_status()

    def zuruecknehmen(self, mahlzeit_id):
        """Mitteilung auf allen Geräten entfernen (Rest ist erfasst)."""
        for dienst in self.ziele(self.optionen_lesen()):
            try:
                self._senden(dienst, {"message": "clear_notification", "data": {"tag": tag(mahlzeit_id)}})
            except requests.RequestException as exc:
                log.warning("Mitteilung bei %s nicht entfernt: %s", dienst, exc)

    def erinnern_einmal(self):
        optionen = self.optionen_lesen()
        minuten = erinnerung_minuten(optionen)
        ziele = self.ziele(optionen) if minuten > 0 else []
        if minuten <= 0 or not ziele:
            return 0
        con = datenbank.verbinden(self.db_pfad)
        try:
            gesendet = 0
            for m in faellige(con, minuten):
                payload = nachricht(m, m["katze_name"], self.panel_pfad)
                for dienst in ziele:
                    try:
                        self._senden(dienst, payload)
                    except requests.RequestException as exc:
                        log.warning("Erinnerung an %s fehlgeschlagen: %s", dienst, exc)
                # auch bei Fehlern als erinnert markieren, damit nicht minütlich erneut gesendet wird
                with con:
                    con.execute("UPDATE mahlzeit SET erinnert = ? WHERE id = ?", (zeit.iso(zeit.jetzt()), m["id"]))
                gesendet += 1
            return gesendet
        finally:
            con.close()

    def warnen_einmal(self):
        """Neue Warnungen (Tierarzt, keine Futteraufnahme, Gewicht, Akzeptanz, Snack-Limit) senden."""
        optionen = self.optionen_lesen()
        if optionen.get("warn_mitteilungen") is False:
            return 0
        ziele = self.ziele(optionen)
        if not ziele:
            return 0

        def senden(payload):
            erfolg = False
            for dienst in ziele:
                try:
                    self._senden(dienst, payload)
                    erfolg = True
                except requests.RequestException as exc:
                    log.warning("Warnung an %s fehlgeschlagen: %s", dienst, exc)
            # nur als gesendet merken, wenn mindestens ein Gerät sie bekommen hat
            return erfolg

        con = datenbank.verbinden(self.db_pfad)
        try:
            return warnungen.pruefen(con, senden, self.panel_pfad)
        finally:
            con.close()

    def _erinnern(self):
        while True:
            try:
                self.erinnern_einmal()
                self.warnen_einmal()
            except requests.RequestException as exc:
                # z. B. während eines Neustarts von Home Assistant
                log.warning("Rest-Erinnerung nicht gesendet (%s), neuer Versuch in 1 Minute", exc)
            except Exception:
                log.exception("Rest-Erinnerung fehlgeschlagen")
            time.sleep(60)

    # --- Antworten empfangen ----------------------------------------------

    def ereignis(self, nachricht_ws):
        """Verarbeitet eine WebSocket-Nachricht; gibt die erfasste mahlzeit_id zurück."""
        if nachricht_ws.get("type") != "event":
            return None
        aktion = (nachricht_ws.get("event") or {}).get("data", {}).get("action")
        con = datenbank.verbinden(self.db_pfad)
        try:
            mahlzeit_id = antwort_verarbeiten(con, aktion)
        finally:
            con.close()
        if aktion_lesen(aktion):
            # Mitteilung überall entfernen, auch wenn der Rest schon vorher erfasst war
            self.zuruecknehmen(aktion_lesen(aktion)[0])
        if mahlzeit_id:
            log.info("Rest per Mitteilung erfasst (Mahlzeit %s)", mahlzeit_id)
            self.bei_aenderung()
        return mahlzeit_id

    def _zuhoeren(self):
        import websocket

        while True:
            try:
                ws = websocket.create_connection(HA_WS, timeout=30)
                try:
                    json.loads(ws.recv())  # auth_required
                    ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    if json.loads(ws.recv()).get("type") != "auth_ok":
                        raise RuntimeError("WebSocket-Anmeldung abgelehnt")
                    ws.send(json.dumps({"id": 1, "type": "subscribe_events",
                                        "event_type": "mobile_app_notification_action"}))
                    log.info("Warte auf Antworten aus Mitteilungen")
                    # Ping alle 2 Minuten, damit eine stumm abgerissene Verbindung auffällt
                    ws.settimeout(120)
                    nummer = 1
                    while True:
                        try:
                            self.ereignis(json.loads(ws.recv()))
                        except websocket.WebSocketTimeoutException:
                            nummer += 1
                            ws.send(json.dumps({"id": nummer, "type": "ping"}))
                finally:
                    ws.close()
            except (OSError, ValueError, RuntimeError, websocket.WebSocketException) as exc:
                # erwartbar bei einem Neustart von Home Assistant: Verbindung weg oder leere Antwort
                log.warning("WebSocket zu Home Assistant getrennt (%s: %s), neuer Versuch in 30 Sekunden",
                            type(exc).__name__, exc)
                time.sleep(30)
            except Exception:
                log.exception("WebSocket unterbrochen, neuer Versuch in 30 Sekunden")
                time.sleep(30)
