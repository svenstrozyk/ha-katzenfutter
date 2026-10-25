"""Tests für Gesundheitsereignisse, Zuordnung und Hinweise."""
import datetime
import importlib
import io
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Sam"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    c.post("/produkt", headers=HEADERS, data={"marke": "Animonda", "sorte": "Rind", "packung_g": "85",
                                              "bestand_packungen": "9", "proteine": "Rind, Huhn"})
    yield c, app_module
    sys.path.pop(0)


def melden(c, typ, **extra):
    return c.post("/gesundheit", headers=HEADERS, data=dict({"typ": typ}, **extra),
                  content_type="multipart/form-data")


def vor(stunden):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=stunden)).isoformat(timespec="seconds")


def zeiten_setzen(mod, tabelle, stunden_liste):
    con = mod.db()
    with con:
        for i, h in enumerate(stunden_liste, start=1):
            con.execute(f"UPDATE {tabelle} SET zeit = ? WHERE id = ?", (vor(h), i))


def test_ereignis_mit_zuordnung_zur_mahlzeit(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "85"})
    r = melden(c, "erbrechen", notiz="nach dem Fressen")
    assert r.status_code == 302
    e = mod.db().execute("SELECT typ, person, erfasst_von, mahlzeit_id, notiz, blut FROM ereignis").fetchone()
    assert tuple(e) == ("erbrechen", "Sam", "Sam", 1, "nach dem Fressen", 0)
    html = c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)
    assert "Erbrechen" in html and "nach Rind" in html


def test_keine_zuordnung_nach_12_stunden(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "85"})
    zeiten_setzen(mod, "mahlzeit", [13])
    melden(c, "durchfall")
    assert mod.db().execute("SELECT mahlzeit_id FROM ereignis").fetchone()[0] is None


def test_haarballen_ohne_zuordnung(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "85"})
    melden(c, "haarballen")
    assert mod.db().execute("SELECT mahlzeit_id FROM ereignis").fetchone()[0] is None


def test_ungueltiger_typ(client):
    c, mod = client
    r = melden(c, "husten")
    assert r.status_code == 400
    assert mod.db().execute("SELECT COUNT(*) FROM ereignis").fetchone()[0] == 0


def test_blut_gibt_tierarzt_hinweis(client):
    c, _ = client
    melden(c, "durchfall", blut="1")
    html = c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)
    assert "Blut bemerkt" in html and "keine Diagnose" in html


def test_mehrfaches_erbrechen(client):
    c, _ = client
    melden(c, "erbrechen")
    assert "Erbrechen in 24 Stunden" not in c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)
    melden(c, "erbrechen")
    assert "2× Erbrechen in 24 Stunden" in c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)


def test_zwei_ereignisse_in_7_tagen_ohne_haarballen(client):
    c, mod = client
    melden(c, "haarballen")
    melden(c, "weicher_kot")
    assert "Ereignisse in 7 Tagen" not in c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)
    melden(c, "erbrechen")
    zeiten_setzen(mod, "ereignis", [100, 100, 30])
    assert "2 Ereignisse in 7 Tagen" in c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)


def test_durchfall_ueber_48_stunden(client):
    c, mod = client
    for _ in range(4):
        melden(c, "durchfall")
    # Abstände 22 h, 22 h, 6 h → Serie über 50 Stunden
    zeiten_setzen(mod, "ereignis", [52, 30, 8, 2])
    assert "Durchfall seit mehr als 48 Stunden" in c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)


def test_durchfall_mit_luecke_ist_neue_serie(client):
    c, mod = client
    for _ in range(2):
        melden(c, "durchfall")
    zeiten_setzen(mod, "ereignis", [60, 2])
    assert "48 Stunden" not in c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)


def test_haeufung_nach_hauptprotein(client):
    c, mod = client
    for _ in range(2):
        c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "40"})
        melden(c, "erbrechen")
    zeiten_setzen(mod, "mahlzeit", [70, 3])
    zeiten_setzen(mod, "ereignis", [69, 2])
    html = c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)
    assert "Ereignisse nach 2 Mahlzeiten mit Rind" in html
    assert "Ereignisse nach 2 Mahlzeiten mit Huhn" in html


def test_zwei_ereignisse_nach_derselben_mahlzeit_sind_keine_haeufung(client):
    c, _ = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "85"})
    melden(c, "erbrechen")
    melden(c, "erbrechen")
    assert "Mahlzeiten mit Rind" not in c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)


def test_futterverweigerung_24_stunden(client):
    c, _ = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "85"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "unberuehrt", "verweigert": "1"})
    assert "nichts gefressen" in c.get("/gesundheit", headers=HEADERS).get_data(as_text=True)


def test_foto_speichern_und_ausliefern(client):
    c, mod = client
    r = melden(c, "erbrechen", foto=(io.BytesIO(b"\xff\xd8bild"), "a.jpg", "image/jpeg"))
    assert r.status_code == 302
    name = mod.db().execute("SELECT foto FROM ereignis").fetchone()[0]
    assert name.endswith(".jpg") and len(name) == 36
    assert c.get(f"/foto?datei={name}", headers=HEADERS).data == b"\xff\xd8bild"


def test_foto_falscher_typ(client):
    c, _ = client
    r = melden(c, "erbrechen", foto=(io.BytesIO(b"x"), "a.pdf", "application/pdf"))
    assert r.status_code == 400


@pytest.mark.parametrize("name", ["../katzenfutter.db", "katzenfutter.db", "abc.jpg", "../../etc/passwd"])
def test_foto_pfade_gesperrt(client, name):
    c, _ = client
    assert c.get(f"/foto?datei={name}", headers=HEADERS).status_code == 404


def test_loeschen_innerhalb_30_minuten(client):
    c, mod = client
    melden(c, "erbrechen", foto=(io.BytesIO(b"\xff\xd8"), "a.jpg", "image/jpeg"))
    name = mod.db().execute("SELECT foto FROM ereignis").fetchone()[0]
    r = c.post("/ereignis_loeschen", headers=HEADERS, data={"ereignis_id": "1"})
    assert "geloescht=1" in r.headers["Location"]
    assert not os.path.exists(os.path.join(mod.FOTO_ORDNER, name))


def test_loeschen_spaeter_nicht_moeglich(client):
    c, mod = client
    melden(c, "erbrechen")
    con = mod.db()
    with con:
        con.execute("UPDATE ereignis SET erfasst = ?", (vor(1),))
    r = c.post("/ereignis_loeschen", headers=HEADERS, data={"ereignis_id": "1"})
    assert "geloescht=0" in r.headers["Location"]
