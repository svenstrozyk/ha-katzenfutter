"""Tests für die Futterdatenbank."""
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}

# Synthetisches Beispiel, keine echte Deklaration
FUTTER = {
    "marke": "Animonda", "linie": "Carny", "sorte": "Rind + Pute", "ean": "", "futterart": "allein",
    "packung_g": "85", "packungstyp": "Schale", "stueck_g": "",
    "rohprotein": "11", "rohfett": "6", "rohasche": "2", "rohfaser": "0,5", "feuchte": "79",
    "kcal_100g": "", "textur": "Pastete", "proteine": "Rind, Pute ,", "fleischanteil": "",
    "getreidefrei": "1", "zuckerfrei": "1", "preis": "1,29", "status": "aktiv",
    "bestand_packungen": "12", "bestand_angebrochen_g": "",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    yield app_module.app.test_client(), app_module
    sys.path.pop(0)


def anlegen(c, **aenderungen):
    return c.post("/produkt", headers=HEADERS, data=dict(FUTTER, **aenderungen))


def test_futter_anlegen_mit_berechneten_kcal(client):
    c, mod = client
    r = anlegen(c)
    assert r.status_code == 302
    assert r.headers["Location"].startswith("/api/hassio_ingress/test/futter")
    p = mod.db().execute("SELECT * FROM produkt").fetchone()
    assert p["kcal_100g"] == pytest.approx(94.75)
    assert p["kcal_herkunft"] == "berechnet"
    assert p["proteine"] == "Rind, Pute"
    assert p["rohfaser"] == 0.5 and p["preis"] == 1.29 and p["getreidefrei"] == 1
    b = mod.db().execute("SELECT packungen, angebrochen_g FROM bestand").fetchone()
    assert tuple(b) == (12, None)


def test_deklarierte_kcal_haben_vorrang(client):
    c, mod = client
    anlegen(c, kcal_100g="98")
    p = mod.db().execute("SELECT kcal_100g, kcal_herkunft FROM produkt").fetchone()
    assert tuple(p) == (98, "deklariert")


def test_ohne_vollstaendige_deklaration_keine_kcal(client):
    c, mod = client
    anlegen(c, rohasche="")
    p = mod.db().execute("SELECT kcal_100g, kcal_herkunft FROM produkt").fetchone()
    assert tuple(p) == (None, None)


def test_liste_und_vergleich(client):
    c, _ = client
    anlegen(c)
    html = c.get("/futter", headers=HEADERS).get_data(as_text=True)
    assert "Animonda Carny Rind + Pute" in html
    assert "95 kcal/100 g (berechnet)" in html
    # Protein auf Trockenmasse: 11 / 21 × 100 = 52 %
    assert "52 %" in html
    assert 'href="/' not in html


def test_bearbeiten_aendert_statt_neu_anzulegen(client):
    c, mod = client
    anlegen(c)
    r = c.post("/produkt", headers=HEADERS, data=dict(FUTTER, id="1", sorte="Pute pur", bestand_packungen="11",
                                                      bestand_angebrochen_g="30"))
    assert r.status_code == 302
    con = mod.db()
    assert con.execute("SELECT COUNT(*) FROM produkt").fetchone()[0] == 1
    assert con.execute("SELECT sorte, geaendert IS NOT NULL FROM produkt").fetchone()[:] == ("Pute pur", 1)
    assert tuple(con.execute("SELECT packungen, angebrochen_g FROM bestand").fetchone()) == (11, 30)


def test_bearbeiten_formular_zeigt_werte(client):
    c, _ = client
    anlegen(c)
    html = c.get("/produkt?id=1", headers=HEADERS).get_data(as_text=True)
    assert 'value="0,5"' in html
    assert "Berechnet: 94,8 kcal/100 g" in html


def test_unbekanntes_produkt_404(client):
    c, _ = client
    assert c.get("/produkt?id=99", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("ean, ok", [("96385074", True), ("036000291452", True), ("4006040000001", False),
                                     ("123", False), ("abcdefgh", False)])
def test_ean_pruefung(client, ean, ok):
    _, mod = client
    assert mod.produkte.ean_gueltig(ean) is ok


def test_doppelte_ean_wird_abgelehnt(client):
    c, mod = client
    assert anlegen(c, ean="96385074").status_code == 302
    r = anlegen(c, ean="9638 5074", sorte="Andere")
    assert r.status_code == 400
    assert "bereits" in r.get_data(as_text=True)
    assert mod.db().execute("SELECT COUNT(*) FROM produkt").fetchone()[0] == 1


def test_neu_mit_vorbelegter_ean(client):
    c, _ = client
    html = c.get("/produkt?ean=96385074", headers=HEADERS).get_data(as_text=True)
    assert 'value="96385074"' in html


@pytest.mark.parametrize("feld, wert", [
    ("marke", ""), ("rohprotein", "120"), ("feuchte", "viel"), ("ean", "4006040000001"),
    ("rohprotein", "15"),  # zusammen mit den übrigen Werten über 100 %
    ("bestand_angebrochen_g", "90"), ("bestand_packungen", "1,5"), ("futterart", "trocken"),
])
def test_ungueltige_eingaben(client, feld, wert):
    c, mod = client
    daten = dict(FUTTER, **{feld: wert})
    if feld == "rohprotein" and wert == "15":
        daten.update(rohfett="8", rohasche="3", rohfaser="1", feuchte="80")
    r = c.post("/produkt", headers=HEADERS, data=daten)
    assert r.status_code == 400
    assert "Nicht gespeichert" in r.get_data(as_text=True)
    assert mod.db().execute("SELECT COUNT(*) FROM produkt").fetchone()[0] == 0


def test_rechner_mit_futter_aus_datenbank(client):
    c, _ = client
    c.post("/katze", headers=HEADERS, data={
        "name": "Mimi", "geburtsjahr": "2023", "kastriert": "1", "freigang": "1",
        "gewicht_aktuell": "4,2", "aktivitaetsfaktor": "1.4"})
    anlegen(c)
    html = c.get("/katze?produkt_id=1", headers=HEADERS).get_data(as_text=True)
    # 287,5 kcal / 94,75 × 100 ≈ 303 g ≈ 3,6 Schalen à 85 g
    assert "Futtermenge Rind + Pute" in html
    assert "303 g" in html and "3,6 × 85 g" in html


def test_snack_erscheint_nicht_im_rechner(client):
    c, _ = client
    c.post("/katze", headers=HEADERS, data={"name": "Mimi", "gewicht_aktuell": "4,2", "aktivitaetsfaktor": "1.4"})
    anlegen(c, futterart="snack", sorte="Leckerli")
    html = c.get("/katze", headers=HEADERS).get_data(as_text=True)
    assert "Leckerli" not in html


def test_vorlage_uebernimmt_werte_ohne_sorte_ean_bestand(client):
    c, _ = client
    anlegen(c, ean="96385074", kcal_100g="98", status="gesperrt")
    html = c.get("/produkt?ean=4006381333931&vorlage=1", headers=HEADERS).get_data(as_text=True)
    assert "Werte aus „Animonda Carny Rind + Pute“ übernommen" in html
    assert 'id="marke" name="marke" required value="Animonda"' in html
    assert 'id="linie" name="linie" value="Carny"' in html
    assert 'id="rohfaser" name="rohfaser" value="0,5"' in html
    assert 'name="kcal_100g" placeholder="falls angegeben"\n             value="98,0"' in html
    # nicht übernommen
    assert 'id="sorte" name="sorte" required value=""' in html
    assert 'value="4006381333931"' in html and "96385074" not in html.split('id="vorlage"')[0]
    assert 'name="bestand_packungen"\n             value=""' in html
    assert '<option value="aktiv" selected>' in html


def test_vorlage_speichern_legt_zweites_futter_an(client):
    c, mod = client
    anlegen(c)
    r = c.post("/produkt", headers=HEADERS, data=dict(FUTTER, sorte="Pute + Herz", ean="96385074"))
    assert r.status_code == 302
    assert mod.db().execute("SELECT COUNT(*) FROM produkt").fetchone()[0] == 2


def test_vorlage_wird_beim_bearbeiten_ignoriert(client):
    c, _ = client
    anlegen(c)
    anlegen(c, marke="Andere Marke", sorte="X")
    html = c.get("/produkt?id=1&vorlage=2", headers=HEADERS).get_data(as_text=True)
    assert "Andere Marke" not in html
    assert 'id="vorlage"' not in html


def test_ohne_futter_keine_vorlagenauswahl(client):
    c, _ = client
    html = c.get("/produkt", headers=HEADERS).get_data(as_text=True)
    assert 'id="vorlage"' not in html
