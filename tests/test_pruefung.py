"""Tests zu den Korrekturen aus der Gesamtprüfung (Personen, Profil, mehrere Katzen, Darstellung)."""
import importlib
import os
import sys

import pytest
from werkzeug.datastructures import MultiDict

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")


def kopf(anzeige, benutzer=""):
    h = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": anzeige}
    if benutzer:
        h["X-Remote-User-Name"] = benutzer
    return h


ALEX = kopf("Alex")
HAUSHALT = MultiDict([("name", "Alex"), ("rolle", "erwachsen"), ("ha_name", ""),
                      ("name", "Sam"), ("rolle", "erwachsen"), ("ha_name", ""),
                      ("name", "Kind 1"), ("rolle", "kind"), ("ha_name", ""), ("snack_limit_kinder", "")])
PROFIL = {"name": "Katze", "geburtsjahr": "2023", "kastriert": "1", "freigang": "1", "gewicht_aktuell": "4,2",
          "aktivitaetsfaktor": "1.4"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    c.post("/einstellungen", headers=ALEX, data=HAUSHALT)
    c.post("/produkt", headers=ALEX, data={"marke": "A", "sorte": "Pute", "packung_g": "85", "bestand_packungen": "3"})
    c.post("/produkt", headers=ALEX, data={"marke": "D", "sorte": "Leckerli", "futterart": "snack", "kcal_100g": "400"})
    yield c, app_module
    sys.path.pop(0)


def optionen(html, feld="person"):
    teil = html.split(f'id="{feld}"')[1].split("</select>")[0]
    return [o.split(">")[1].split("<")[0] for o in teil.split("<option")[1:]]


@pytest.mark.parametrize("kopfzeilen", [kopf("Sam Muster"), kopf("L. S.", "sam"), kopf("sam")])
def test_sam_wird_erkannt_ohne_doppelung(client, kopfzeilen):
    c, mod = client
    html = c.get("/fuettern", headers=kopfzeilen).get_data(as_text=True)
    assert optionen(html) == ["Alex", "Sam", "Kind 1"]
    assert '<option value="Sam" selected>' in html
    # darf Einstellungen ändern
    assert c.post("/einstellungen", headers=kopfzeilen, data=HAUSHALT).status_code == 302


def test_unbekannter_benutzer_einmal_vorne(client):
    c, _ = client
    html = c.get("/snack", headers=kopf("Oma Erika")).get_data(as_text=True)
    assert optionen(html) == ["Oma Erika", "Alex", "Sam", "Kind 1"]


def test_vorname_nicht_eindeutig_keine_zuordnung(client):
    c, mod = client
    c.post("/einstellungen", headers=ALEX, data=MultiDict(list(HAUSHALT.items(multi=True)) + [
        ("name", "Sam M."), ("rolle", "erwachsen"), ("ha_name", "")]))
    einst = mod.einstellungen.laden(mod.db())
    assert mod.einstellungen.person_zu_benutzer(einst, ["Sam Muster", ""])["name"] == "Sam"
    assert mod.einstellungen.person_zu_benutzer(einst, ["Sam M.", ""])["name"] == "Sam M."


def test_einstellungen_eine_leere_zeile_und_rollentext(client):
    c, _ = client
    html = c.get("/einstellungen", headers=ALEX).get_data(as_text=True)
    assert html.count('class="card person neu"') == 1 and "Weitere Person" in html
    assert ">Erwachsen<" in html and "Erwachsener" not in html
    assert "erkannt als <strong>Alex</strong>" in html
    assert "pro Tag und Katze" in html
    # kein Katzen-Umschalter auf der Haushaltsseite
    assert 'class="katzenwahl"' not in html


def test_profil_ueberschreibt_kein_neueres_gewicht(client):
    c, mod = client
    c.post("/katze", headers=ALEX, data=PROFIL)
    con = mod.db()
    # PetKit misst zwischendurch 4,25 kg
    with con:
        con.execute("UPDATE katze SET gewicht_aktuell = 4.25")
    # Formular mit altem Wert 4,20 (gewicht_vorher = 4,20) speichern, nur Name geändert
    c.post("/katze", headers=ALEX, data=dict(PROFIL, name="Katze", gewicht_vorher="4,20"))
    assert con.execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] == 4.25
    assert con.execute("SELECT COUNT(*) FROM gewicht").fetchone()[0] == 1
    # bewusst geänderter Wert gilt
    c.post("/katze", headers=ALEX, data=dict(PROFIL, gewicht_aktuell="4,3", gewicht_vorher="4,25"))
    assert con.execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] == 4.3


def test_formular_enthaelt_gewicht_vorher(client):
    c, _ = client
    c.post("/katze", headers=ALEX, data=PROFIL)
    assert 'name="gewicht_vorher" value="4,20"' in c.get("/katze", headers=ALEX).get_data(as_text=True)


@pytest.mark.parametrize("jahr", ["23", "1850", "2999"])
def test_geburtsjahr_geprueft(client, jahr):
    c, _ = client
    r = c.post("/katze", headers=ALEX, data=dict(PROFIL, geburtsjahr=jahr))
    assert r.status_code == 400 and "Geburtsjahr" in r.get_data(as_text=True)


def test_katze_anlegen_doppelt_und_leer(client):
    c, mod = client
    assert "fehler_neu=2" in c.post("/katze_neu", headers=ALEX, data={"name": "katze"}).headers["Location"]
    assert "fehler_neu=1" in c.post("/katze_neu", headers=ALEX, data={"name": ""}).headers["Location"]
    html = c.get("/katze?fehler_neu=2", headers=ALEX).get_data(as_text=True)
    assert "gibt es schon" in html


def test_katze_ausblenden_und_menue(client):
    c, mod = client
    html = c.get("/katze", headers=ALEX).get_data(as_text=True)
    assert "Ausblenden" not in html and "    Katzen</a>" in html
    c.post("/katze_neu", headers=ALEX, data={"name": "Mimi"})
    html = c.get("/katze", headers=ALEX).get_data(as_text=True)
    assert "Ausblenden" in html and "    Katzen</a>" in html and '<span class="titel">Katze</span>' in html
    r = c.post("/katze_entfernen", headers=ALEX, data={"id": "2"})
    assert "entfernt=1" in r.headers["Location"]
    assert mod.db().execute("SELECT aktiv FROM katze WHERE id = 2").fetchone()[0] == 0
    # letzte Katze bleibt
    r = c.post("/katze_entfernen", headers=ALEX, data={"id": "1"})
    assert "entfernt=0" in r.headers["Location"]
    assert mod.db().execute("SELECT aktiv FROM katze WHERE id = 1").fetchone()[0] == 1


def test_umschalter_nur_auf_seiten_je_katze(client):
    c, mod = client
    c.post("/katze_neu", headers=ALEX, data={"name": "Mimi"})
    c.post("/fuettern", headers=ALEX, data={"produkt_id": "1", "menge_g": "85"})
    for pfad in ["/", "/fuettern", "/snack", "/gesundheit", "/futter", "/kosten", "/verlauf", "/katze"]:
        assert 'class="katzenwahl"' in c.get(pfad, headers=ALEX).get_data(as_text=True), pfad
    for pfad in ["/einstellungen", "/produkt?id=1", "/rest?id=1", "/scan"]:
        assert 'class="katzenwahl"' not in c.get(pfad, headers=ALEX).get_data(as_text=True), pfad
    assert "<span class=\"label\">Katze</span><span class=\"wert\">" in c.get("/rest?id=1", headers=ALEX).get_data(as_text=True)


@pytest.mark.parametrize("zurueck, ziel", [("snack", "/snack"), ("gesundheit", "/gesundheit"), ("kosten", "/kosten"),
                                           ("unsinn", "/")])
def test_umschalten_bleibt_auf_der_seite(client, zurueck, ziel):
    c, _ = client
    c.post("/katze_neu", headers=ALEX, data={"name": "Mimi"})
    r = c.post("/katze_waehlen", headers=ALEX, data={"id": "1", "zurueck": zurueck})
    assert r.headers["Location"].endswith("/api/hassio_ingress/test" + ziel)


def test_einzahl_packung(client):
    c, _ = client
    c.post("/produkt", headers=ALEX, data={"id": "1", "marke": "A", "sorte": "Pute", "packung_g": "85", "bestand_packungen": "1"})
    html = c.get("/fuettern", headers=ALEX).get_data(as_text=True)
    assert "1 Packung à 85 g" in html and "1 Packungen" not in html


def test_kein_veralteter_hinweis(client):
    c, _ = client
    c.post("/katze", headers=ALEX, data=PROFIL)
    assert "Ab Schritt 4" not in c.get("/katze", headers=ALEX).get_data(as_text=True)


def test_textur_gross_klein_gleich(client):
    _, mod = client
    m = {"produkt_id": 1, "marke": "A", "textur": "pastete", "proteine": ""}
    assert mod.praeferenz._schluessel(m, "textur") == ["Pastete"]
    assert mod.praeferenz._schluessel(dict(m, textur="Stückchen in Gelee"), "textur") == ["Stückchen in Gelee"]


def test_person_entfernen(client):
    c, mod = client
    html = c.get("/einstellungen", headers=ALEX).get_data(as_text=True)
    assert html.count('class="chip entfernen"') == 3 and 'data-name="Kind 1"' in html
    # „Entfernen“ leert den Namen; beim Speichern fällt die Person weg
    daten = MultiDict([("name", "Alex"), ("rolle", "erwachsen"), ("ha_name", ""),
                       ("name", "Sam"), ("rolle", "erwachsen"), ("ha_name", ""),
                       ("name", ""), ("rolle", "kind"), ("ha_name", ""), ("snack_limit_kinder", "")])
    assert c.post("/einstellungen", headers=ALEX, data=daten).status_code == 302
    assert [p["name"] for p in mod.einstellungen.laden(mod.db())["personen"]] == ["Alex", "Sam"]


def test_menue_heisst_immer_katzen(client):
    c, _ = client
    html = c.get("/", headers=ALEX).get_data(as_text=True)
    assert "    Katzen</a>" in html and "frameElement" in html


def test_verweigert_eigenes_formular(client):
    c, _ = client
    c.post("/fuettern", headers=ALEX, data={"produkt_id": "1", "menge_g": "85"})
    html = c.get("/rest?id=1", headers=ALEX).get_data(as_text=True)
    schaetz_form = html.split("<h2>Geschätzt</h2>")[1].split("</form>")[0]
    assert 'name="verweigert"' not in schaetz_form and "onclick" not in schaetz_form
    assert '<input type="hidden" name="verweigert" value="1">' in html


def test_mahlzeit_loeschen_mit_und_ohne_bestand(client):
    c, mod = client
    con = mod.db()
    bestand = lambda: tuple(con.execute("SELECT packungen, angebrochen_g FROM bestand WHERE produkt_id = 1").fetchone())
    c.post("/fuettern", headers=ALEX, data={"produkt_id": "1", "menge_g": "40"})
    c.post("/fuettern", headers=ALEX, data={"produkt_id": "1", "menge_g": "40"})
    assert bestand() == (2, 5)
    # ältere Mahlzeit: gelöscht, Bestand bleibt
    r = c.post("/mahlzeit_loeschen", headers=ALEX, data={"id": "1"})
    assert "geloescht=ohne_bestand" in r.headers["Location"] and bestand() == (2, 5)
    # jüngste: Bestand zurück (5 g + 40 g angebrochen)
    r = c.post("/mahlzeit_loeschen", headers=ALEX, data={"id": "2"})
    assert "geloescht=mit_bestand" in r.headers["Location"] and bestand() == (2, 45)
    assert con.execute("SELECT COUNT(*) FROM mahlzeit").fetchone()[0] == 0
    assert c.post("/mahlzeit_loeschen", headers=ALEX, data={"id": "99"}).status_code == 404


def test_geloeschte_mahlzeit_loest_ereignis_zuordnung(client):
    c, mod = client
    c.post("/fuettern", headers=ALEX, data={"produkt_id": "1", "menge_g": "40"})
    c.post("/gesundheit", headers=ALEX, data={"typ": "erbrechen"}, content_type="multipart/form-data")
    c.post("/mahlzeit_loeschen", headers=ALEX, data={"id": "1"})
    assert mod.db().execute("SELECT mahlzeit_id FROM ereignis").fetchone()[0] is None


def test_wiegung_verwerfen_und_zulassen(client):
    c, mod = client
    c.post("/katze", headers=ALEX, data=PROFIL)
    c.post("/verlauf", headers=ALEX, data={"kg": "5,9"})  # Tippfehler
    con = mod.db()
    assert con.execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] == 5.9
    falsch = con.execute("SELECT id FROM gewicht WHERE kg = 5.9").fetchone()[0]
    assert "Letzte Wiegungen" in c.get("/verlauf", headers=ALEX).get_data(as_text=True)
    c.post("/wiegung_umschalten", headers=ALEX, data={"id": falsch})
    assert con.execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] == 4.2
    c.post("/wiegung_umschalten", headers=ALEX, data={"id": falsch})
    assert con.execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] == 5.9


def test_snack_ohne_bestandsangabe(client):
    c, _ = client
    html = c.get("/futter", headers=ALEX).get_data(as_text=True)
    zeile = html.split("Leckerli")[1].split("</a>")[0]
    assert "Bestand" not in zeile


def test_katzenname_sicher_in_abfrage(client):
    c, _ = client
    c.post("/katze", headers=ALEX, data=dict(PROFIL, name="D'Art\"a"))
    c.post("/katze_neu", headers=ALEX, data={"name": "Mimi"})
    html = c.get("/katze", headers=ALEX).get_data(as_text=True)
    assert "confirm(&#34;D\\u0027Art\\&#34;a ausblenden?" in html


def test_uhrzeit_nach_mitternacht_ist_gestern(client, monkeypatch):
    c, mod = client
    import datetime as dt
    jetzt = dt.datetime(2026, 10, 26, 0, 10, tzinfo=mod.zeit.BERLIN)
    monkeypatch.setattr(mod.zeit, "jetzt", lambda: jetzt.astimezone(dt.timezone.utc))
    zeitpunkt, fehler = mod.uhrzeit_lesen("23:30")
    assert fehler is None and zeitpunkt.astimezone(mod.zeit.BERLIN) == dt.datetime(2026, 10, 25, 23, 30, tzinfo=mod.zeit.BERLIN)
    zeitpunkt, _ = mod.uhrzeit_lesen("00:05")
    assert zeitpunkt.astimezone(mod.zeit.BERLIN).day == 26
