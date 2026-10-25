"""Tests für Rest-Erinnerung und Antworten aus Mitteilungen (ohne Netzwerk)."""
import datetime
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Sam"}
OPTIONEN = {"notify_services": ["mobile_app_iphone_alex", "notify.mobile_app_sams_iphone"],
            "rest_erinnerung_minuten": 30}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    c.post("/produkt", headers=HEADERS, data={"marke": "Animonda", "sorte": "Pute", "packung_g": "85",
                                              "kcal_100g": "100", "bestand_packungen": "5"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "85"})
    yield c, app_module
    sys.path.pop(0)


def vor(minuten):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minuten)).isoformat(timespec="seconds")


def mahlzeit_alter(mod, minuten, mahlzeit_id=1):
    con = mod.db()
    with con:
        con.execute("UPDATE mahlzeit SET zeit = ? WHERE id = ?", (vor(minuten), mahlzeit_id))


@pytest.fixture()
def dienst(client, monkeypatch):
    _, mod = client
    gesendet = []
    d = mod.benachrichtigung.Dienst(mod.DB_PATH, "token", lambda: OPTIONEN, "/4f1ea0a0_katzenfutter")
    monkeypatch.setattr(d, "_senden", lambda dienst_name, payload: gesendet.append((dienst_name, payload)))
    d.gesendet = gesendet
    return d


def test_empfaenger_und_vorgaben(client):
    _, mod = client
    b = mod.benachrichtigung
    assert b.empfaenger(OPTIONEN) == ["mobile_app_iphone_alex", "mobile_app_sams_iphone"]
    assert b.empfaenger({}) == []
    assert b.empfaenger({}) == []
    assert b.erinnerung_minuten({}) == 30 and b.erinnerung_minuten({"rest_erinnerung_minuten": 0}) == 0


def test_noch_nicht_faellig(client, dienst):
    _, mod = client
    mahlzeit_alter(mod, 10)
    assert dienst.erinnern_einmal() == 0 and dienst.gesendet == []


def test_erinnerung_an_alle_empfaenger_genau_einmal(client, dienst):
    _, mod = client
    mahlzeit_alter(mod, 31)
    assert dienst.erinnern_einmal() == 1
    assert [d for d, _ in dienst.gesendet] == ["mobile_app_iphone_alex", "mobile_app_sams_iphone"]
    payload = dienst.gesendet[0][1]
    assert payload["title"] == "Hat Katze aufgefressen?"
    assert "85 g Pute" in payload["message"] and "Sam" in payload["message"]
    aktionen = [a["action"] for a in payload["data"]["actions"]]
    assert aktionen[:2] == ["KATZENFUTTER_REST|1|nichts", "KATZENFUTTER_REST|1|wenig"]
    assert payload["data"]["actions"][-1] == {"action": "URI", "title": "Wiegen …", "uri": "/4f1ea0a0_katzenfutter"}
    assert payload["data"]["tag"] == "katzenfutter-rest-1"
    # beim nächsten Durchlauf nicht erneut
    assert dienst.erinnern_einmal() == 0


def test_keine_erinnerung_fuer_alte_oder_erfasste_mahlzeiten(client, dienst):
    c, mod = client
    mahlzeit_alter(mod, 13 * 60)
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "40"})
    mahlzeit_alter(mod, 60, mahlzeit_id=2)
    c.post("/rest", headers=HEADERS, data={"id": "2", "stufe": "nichts"})
    assert dienst.erinnern_einmal() == 0


def test_erinnerung_abschaltbar(client, monkeypatch):
    _, mod = client
    mahlzeit_alter(mod, 60)
    d = mod.benachrichtigung.Dienst(mod.DB_PATH, "t", lambda: dict(OPTIONEN, rest_erinnerung_minuten=0), "/")
    monkeypatch.setattr(d, "_senden", lambda *a: pytest.fail("darf nicht senden"))
    assert d.erinnern_einmal() == 0


def test_antwort_traegt_rest_ein_und_entfernt_mitteilung(client, dienst):
    _, mod = client
    geaendert = []
    dienst.bei_aenderung = lambda: geaendert.append(1)
    ereignis = {"type": "event", "event": {"event_type": "mobile_app_notification_action",
                                           "data": {"action": "KATZENFUTTER_REST|1|wenig"}}}
    assert dienst.ereignis(ereignis) == 1
    m = mod.db().execute("SELECT rest_g, rest_herkunft, gefressen_g, kcal FROM mahlzeit WHERE id = 1").fetchone()
    assert tuple(m) == (8.5, "geschaetzt", 76.5, 76.5)
    assert geaendert == [1]
    entfernt = [(d, p) for d, p in dienst.gesendet if p["message"] == "clear_notification"]
    assert len(entfernt) == 2 and entfernt[0][1]["data"]["tag"] == "katzenfutter-rest-1"


def test_zweite_antwort_ueberschreibt_nicht(client, dienst):
    _, mod = client
    dienst.ereignis({"type": "event", "event": {"data": {"action": "KATZENFUTTER_REST|1|nichts"}}})
    assert dienst.ereignis({"type": "event", "event": {"data": {"action": "KATZENFUTTER_REST|1|unberuehrt"}}}) is None
    assert mod.db().execute("SELECT rest_g FROM mahlzeit WHERE id = 1").fetchone()[0] == 0


@pytest.mark.parametrize("aktion", [None, "", "ANDERE_AKTION", "KATZENFUTTER_REST|x|wenig",
                                    "KATZENFUTTER_REST|1|ein_bisschen", "KATZENFUTTER_REST|99|wenig"])
def test_fremde_oder_ungueltige_aktionen(client, dienst, aktion):
    _, mod = client
    assert dienst.ereignis({"type": "event", "event": {"data": {"action": aktion}}}) is None
    assert mod.db().execute("SELECT rest_g FROM mahlzeit WHERE id = 1").fetchone()[0] is None


def test_nicht_ereignis_nachrichten_werden_ignoriert(client, dienst):
    assert dienst.ereignis({"type": "result", "success": True}) is None
    assert dienst.ereignis({"type": "pong"}) is None


def test_rest_in_app_entfernt_mitteilung(client):
    c, mod = client
    aufrufe = []

    class Fake:
        def zuruecknehmen(self, mahlzeit_id):
            aufrufe.append(mahlzeit_id)

    mod.mitteilung_dienst = Fake()
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "haelfte"})
    for t in list(mod.threading.enumerate()):
        if t is not mod.threading.current_thread() and t.daemon and t.name.startswith("Thread"):
            t.join(timeout=2)
    assert aufrufe == [1]
    mod.mitteilung_dienst = None


def test_kein_dienst_im_entwicklungsmodus(client):
    _, mod = client
    assert mod.mitteilung_dienst is None


class _Abbruch(Exception):
    pass


def test_verbindungsfehler_nur_als_warnung(client, monkeypatch, caplog):
    _, mod = client
    websocket = pytest.importorskip("websocket")

    def verbinden(*a, **k):
        raise ConnectionRefusedError("Core startet neu")

    def schlafen(sekunden):
        raise _Abbruch()

    monkeypatch.setattr(websocket, "create_connection", verbinden)
    monkeypatch.setattr(mod.benachrichtigung.time, "sleep", schlafen)
    d = mod.benachrichtigung.Dienst(mod.DB_PATH, "t", lambda: OPTIONEN, "/")
    with caplog.at_level("WARNING"), pytest.raises(_Abbruch):
        d._zuhoeren()
    eintrag = [r for r in caplog.records if r.name == "katzenfutter.mitteilung"][-1]
    assert eintrag.levelname == "WARNING" and eintrag.exc_info is None
    assert "Core startet neu" in eintrag.getMessage()


class Antwort:
    def __init__(self, daten):
        self.daten = daten

    def raise_for_status(self):
        pass

    def json(self):
        return self.daten


def test_ohne_empfaenger_alle_handys_mit_app(client, monkeypatch):
    _, mod = client
    b = mod.benachrichtigung
    aufrufe = []

    def holen(url, **_):
        aufrufe.append(url)
        return Antwort([{"domain": "light", "services": {}},
                        {"domain": "notify", "services": {"mobile_app_handy_b": {}, "persistent_notification": {},
                                                          "mobile_app_handy_a": {}}}])

    monkeypatch.setattr(b.requests, "get", holen)
    dienst = b.Dienst(mod.DB_PATH, "token", lambda: {}, "/x")
    assert dienst.ziele({"notify_services": []}) == ["mobile_app_handy_a", "mobile_app_handy_b"]
    assert dienst.ziele({}) == ["mobile_app_handy_a", "mobile_app_handy_b"]
    assert len(aufrufe) == 1  # zwischengespeichert
    assert dienst.ziele({"notify_services": ["notify.x"]}) == ["x"]


def test_ohne_ha_keine_empfaenger(client, monkeypatch):
    _, mod = client
    b = mod.benachrichtigung

    def fehler(*_a, **_k):
        raise b.requests.ConnectionError("weg")

    monkeypatch.setattr(b.requests, "get", fehler)
    assert b.Dienst(mod.DB_PATH, "token", lambda: {}, "/x").ziele({}) == []
