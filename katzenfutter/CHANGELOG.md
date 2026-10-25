# Changelog

## 0.25.0 – 2026-10-25

- Füttern: Menge steht standardmäßig auf einer ganzen Packung (auch wenn eine Packung angebrochen ist;
  der Bestand nimmt zuerst die angebrochene)
- Füttern: kürzere Sortenliste. Oben höchstens vier vorrätige Sorten (angebrochene zuerst, dann zuletzt
  gefüttert), alle übrigen unter „Weitere Sorten“ nach Marke gruppiert, nicht vorrätige zuletzt; ab sieben
  weiteren Sorten mit Suchfeld

## 0.24.0 – 2026-10-25

- Zum Teilen vorbereitet: keine persönlichen Vorgaben mehr. Neue Installationen beginnen mit einer Katze „Katze“
  (Name im Profil ändern); bestehende Installationen bleiben unverändert
- `notify_services` darf leer bleiben: Mitteilungen gehen dann an alle Handys mit Home-Assistant-App
- Tageskopien der Datenbank liegen jetzt im Konfigurationsordner des Add-ons
  (`addon_configs/<kennung>_katzenfutter/sicherung/`, per Samba oder SSH erreichbar)
- Kopie einspielen: dort in `wiederherstellen.db` umbenennen und Add-on neu starten; die bisherige Datenbank
  wird vorher als `vor-wiederherstellung-<Zeit>.db` beiseitegelegt, ungültige Dateien werden abgelehnt
- Screenshots und Beispiele mit erfundenen Namen

## 0.23.0 – 2026-10-25

- Rechte: Profil, Futter und Bestand, Katzen, Wiegungen, Mahlzeiten löschen und Einstellungen ändern nur noch
  Erwachsene; Kinder füttern, tragen Reste und Snacks ein, melden Gesundheit und sehen alles. Ohne angelegte
  Personen bleibt alles für alle offen
- Tägliche vollständige Kopie der Datenbank unter `/data/sicherung/` (7 Tage), zusätzlich zum HA-Backup
- Entfernt: Technik-Test-Seite samt Prüf-Schnittstellen und Option `notify_service`
- Entfernt: Texterkennung per Foto (Tesseract); Deklaration per Live Text einfügen bleibt. Image deutlich kleiner

## 0.22.4 – 2026-10-25

- Behoben: Nach Mitternacht nachgetragene Uhrzeit (z. B. 23:30 um 0:10) wurde als „in der Zukunft“ abgelehnt;
  sie gilt jetzt als gestern (Füttern, Gesundheit)

## 0.22.3 – 2026-10-25

- Behoben: „Verweigert – nicht angerührt“ konnte nach Zurück im Browser den nächsten Rest fälschlich als
  verweigert speichern (eigenes Formular statt JavaScript)
- Behoben: Katzenname mit Apostroph oder Anführungszeichen brach die Sicherheitsabfrage beim Ausblenden
- Mahlzeit löschen auch nach 30 Minuten (Rest-Seite); Bestand wird zurückgerechnet, wenn es die letzte
  Mahlzeit der Sorte ist
- Wiegungen im Verlauf verwerfen oder wieder zulassen; Profilgewicht folgt der jüngsten gültigen Wiegung
- Snacks im Tab Futter ohne irreführende Bestandsangabe
- Vorlieben-Berechnung rund 50-mal schneller (Binärsuche statt Vergleich aller Mahlzeiten); wichtig, weil sie
  jede Minute für Sensoren und Warnungen läuft

## 0.22.2 – 2026-10-25

- Tab-Leiste: flacher (Höhe wie in iOS) und in der Farbe des HA-Hintergrunds darunter, damit sie mit dem
  Streifen über dem Home-Balken eine Fläche bildet
- Menü heißt durchgehend „Katzen“
- Einstellungen: Knopf „Entfernen“ je Person (wirksam mit „Speichern“)

## 0.22.1 – 2026-10-25

Gesamtprüfung nach den Erweiterungen:

- Personen: angemeldeter HA-Benutzer wird auch über Benutzername und Vorname erkannt („Alex Muster“ → Alex);
  keine Doppelung mehr in „gefüttert/gegeben von“, Einstellungen zeigen, als wer man erkannt wurde
- Einstellungen: eine leere Zeile plus „Weitere Person“ statt zwei leerer Karten; Rolle „Erwachsen“ / „Kind“;
  Snack-Limit ausdrücklich je Katze
- Auswahlfelder: Pfeil direkt am Wert, keine verdrehte Darstellung mehr
- Tab-Leiste ohne doppelten Abstand zum unteren Rand (Home Assistant hält den Home-Balken selbst frei)
- Mehrere Katzen: Umschalter beschriftet und nur auf Seiten je Katze; Menü „Katzen“; Abschnitt „Katzen im Haushalt“
  mit Ausblenden (Daten bleiben); Hinweis bei leerem oder doppeltem Namen; Katze in Rest und Akzeptanz genannt;
  nach dem Umschalten bleibt man auf Snack, Gesundheit oder Kosten
- Profil: Speichern überschreibt kein inzwischen gemessenes Gewicht mehr; Geburtsjahr wird geprüft
- Vorlieben: Texturen unabhängig von der Großschreibung am Wortanfang zusammengefasst
- Texte: „1 Packung“, veralteter Hinweis im Rechner entfernt

## 0.22.0 – 2026-10-25

- PetKit-Katzenklo vorbereitet: im Profil je Katze Sensor „letzter Toilettengang“ und „Gewicht je Toilettengang“
  wählen (Vorschläge aus Home Assistant)
- Abgleich alle 5 Minuten über den HA-Verlauf seit dem letzten Stand (erster Abgleich: 7 Tage), doppelte
  Werte werden erkannt
- Gewicht: Einheiten g/kg/lb, Ausreißer > 5 % zum 7-Tage-Median verworfen (gespeichert, markiert);
  fließt in Verlauf, Trend, Gewichtshinweise und „3 Tage kein Wert von der Toilette“ ein
- Toilettengänge: Anzahl der letzten 24 Stunden auf Heute; Hinweis und Mitteilung bei deutlich mehr Gängen
  als üblich (≥ 6 und mindestens doppelt so viele wie im 14-Tage-Mittel); bewusst kein Hinweis bei wenigen Gängen (Freigang)
- Migration 11: Sensoren und Abgleichstand je Katze

## 0.21.1 – 2026-10-25

- Behoben: Werden bei einem Futter kcal/100 g oder Stückgewicht geändert, werden die kcal der bereits erfassten
  Mahlzeiten und Snacks dieses Futters neu berechnet (bisher blieben sie auf dem Stand beim Erfassen)
- Von Hand eingetragene Snack-Gramm bleiben dabei erhalten
- Migration 10: fehlende kcal aus inzwischen ergänzten Futterdaten einmalig nachgetragen

## 0.21.0 – 2026-10-25

- Warn-Mitteilungen an alle Empfänger: Tierarzt-Hinweise (zeitkritisch, auch im Fokus-Modus), keine
  Futteraufnahme, Gewichts- und Akzeptanzhinweise, überschrittenes Snack-Limit der Kinder
- Jede Warnung einmal; nach dem Verschwinden meldet ein erneutes Auftreten wieder; geänderte Zahlen
  („3× statt 2×“) lösen keine neue Mitteilung aus
- Fehlgeschlagener Versand wird beim nächsten Durchlauf wiederholt
- Neue Option `warn_mitteilungen` (Vorgabe an)

## 0.20.1 – 2026-10-25

- Anzeige: Textur in Originalschreibweise („Stückchen in Gelee“), kein Umbruch in Kennzeichen und
  Tabellenwerten, doppelter Punkt nach dem Datum der letzten Wiegung entfernt
- Beschreibung des Add-ons aktualisiert

## 0.20.0 – 2026-10-25

- Vorgebaute Images für aarch64 und amd64 (GitHub Actions, ghcr.io): Updates werden heruntergeladen statt
  auf dem Pi gebaut
- Tests laufen bei jedem Push in GitHub Actions mit Python 3.12
- Mehrere Katzen: weitere Katze im Tab Katze anlegen, Umschalter oben auf jeder Seite (Auswahl je Gerät);
  Futter und Bestand gemeinsam, Mahlzeiten, Snacks, Gesundheit, Gewicht und Vorlieben je Katze
- Protokoll: Verbindungsabbrüche bei einem Neustart von Home Assistant oder Mosquitto als einzeilige
  Warnung statt Fehler mit Traceback

## 0.19.0 – 2026-10-25

- Kostenauswertung (Tab Futter → „Kosten“, auch aus Verlauf): Summe, Ø pro Tag, Hochrechnung pro Monat,
  im Napf übrig gebliebener Anteil, je Sorte (inkl. Snacks) und je Kalendermonat; Zeitraum 30 oder 90 Tage
- Preisvergleich der aktiven Sorten je 100 g und je 100 kcal
- Sorten ohne Preis oder Packungsgröße werden benannt und nicht mitgerechnet
- Neuer Sensor `sensor.<katze>_futterkosten_30_tage` (EUR)

## 0.18.0 – 2026-10-25

- Einstellungen → „Schwellen für Hinweise“: keine Futteraufnahme (h), Gewichtsverlust je Woche und
  4 Wochen, Gewichtszunahme 4 Wochen, Akzeptanzeinbruch, Lieblingsfutter (Score, Mahlzeiten),
  „wird nicht gemocht“ (Score, Mahlzeiten, Verweigerungen); leer = Standard, ändern nur Erwachsene
- Gespeichert werden nur Abweichungen vom Standard
- Fest bleiben Tierarzt-Hinweise und die 10-%-Grenze für Snacks

## 0.17.0 – 2026-10-25

- Produktdaten per EAN aus Open Pet Food Facts (Ersatz: Open Food Facts): nach dem Scan einer unbekannten
  EAN automatisch, sonst über „Daten zur EAN suchen“; füllt nur leere Felder (Marke, Sorte, Packung,
  Deklaration, kcal, Hauptproteine, Snack, getreidefrei) und markiert sie; gespeichert wird erst nach Prüfung
- Übertragen wird nur die EAN; abschaltbar über die Option `online_produktdaten`
- Abdeckung ist lückenhaft: fehlt die Deklaration, bleibt Live Text oder Eintippen

## 0.16.2 – 2026-10-25

- Neuer empfohlener Weg für die Deklaration: „Text einfügen (Live Text vom iPhone)“ – Text in Kamera
  oder Fotos markieren, kopieren, einfügen; dieselbe Auswertung belegt die Felder vor
- Texterkennung auf dem Pi: höhere Auflösung (bis 3200 px) und bis zu drei Durchläufe mit
  unterschiedlicher Seitenaufteilung, gewählt wird das Ergebnis mit den meisten sicheren Werten

## 0.16.1 – 2026-10-25

- Texterkennung: mehrsprachige Etiketten („Fettgehalt/Teneur en matières grasses/… 4,5 %“) werden erkannt;
  zwischen Bezeichnung und Wert sind jetzt Übersetzungen erlaubt, aber keine andere Bezeichnung
- Unsicher gelesene Werte (Komma ohne Nachkommastelle, verlesene „1“ wie „]“) werden nicht eingetragen,
  sondern mit Ausschnitt gemeldet („bitte von der Packung abtippen“)
- Echter Erkennungstext eines Animonda-Etiketts als Testfall

## 0.16.0 – 2026-10-25

- Texterkennung der Deklaration: im Formular „Futter“ → „Deklaration fotografieren“
- Foto wird im Browser verkleinert und als Graustufen-JPEG gesendet (auch HEIC vom iPhone),
  auf dem Pi mit Tesseract (Deutsch) gelesen und danach verworfen
- Vorbelegt werden Rohprotein, Rohfett, Rohasche, Rohfaser, Feuchte, kcal/100 g (auch aus kcal/kg),
  Hauptproteine aus der Zusammensetzung, getreidefrei, zuckerfrei; markiert, gespeichert erst nach Prüfung
- Erkannter Rohtext zur Kontrolle aufklappbar
- Neue Systempakete: tesseract-ocr, tesseract-ocr-data-deu (Alpine, fertig gebaut)

## 0.15.0 – 2026-10-25

- Präferenzerkennung: Akzeptanz je Mahlzeit gegen die 14-Tage-Baseline über alle Futter; Gewichte
  gewogen 1,0 / geschätzt 0,6, erste Mahlzeit nach > 12 h Pause und die ersten zwei einer neuen Sorte halb;
  Score = Σ w(a − Baseline) / (Σ w + 3)
- Einstufung je Sorte, Marke, Textur und Hauptprotein: Lieblingsfutter (≥ +0,10 bei ≥ 5 Mahlzeiten),
  „wird nicht gemocht“ (≤ −0,20 bei ≥ 3 Mahlzeiten oder 2× verweigert), neutral, noch zu wenig Daten
- Anzeige im Tab Futter (Kennzeichen je Sorte, Abschnitt „Vorlieben“) und je Futter („Akzeptanz“)
- „Sorte sperren“ nur auf Knopfdruck bei „wird nicht gemocht“, nie automatisch
- Hinweis bei Akzeptanzeinbruch über alle Futter (eher Gesundheit oder Fremdfütterung) auf Heute,
  im Tab Futter und im MQTT-Attribut „hinweise“
- Migration 9: Tabelle praeferenz

## 0.14.0 – 2026-10-25

- Tab Verlauf (7 / 30 / 90 Tage): Gewicht als Tagesmedian mit gleitendem 7-Tage-Trend, kcal je Tag
  (Futter und Snacks gestapelt, Bedarf als Linie, geschätzte Tage schraffiert), Tabelle, Gesundheitsereignisse
- Antippen oder Überfahren zeigt Werte eines Tages
- Gewicht schnell eintragen (mit Datum); das Profilgewicht folgt der jüngsten Wiegung
- Gewichtshinweise: Verlust > 2 % in einer Woche, > 5 % in 4 Wochen, Zunahme > 5 % in 4 Wochen
  (Vergleich der Trendwerte, Referenz höchstens 3 Tage vom Stichtag entfernt); auf Heute und im
  MQTT-Attribut „hinweise“
- Vorbereitet für PetKit: Ausreißerregel (> 5 % zum 7-Tage-Median), Hinweis bei 3 Tagen ohne Wert

## 0.13.0 – 2026-10-25

- Rest-Erinnerung: Mitteilung „Hat <Katze> aufgefressen?“ an alle Empfänger, standardmäßig 30 Minuten
  nach einer Mahlzeit ohne erfassten Rest (Option `rest_erinnerung_minuten`, 0 = aus)
- Aktionen: Alles gefressen, Wenig, Hälfte, Viel übrig, Unberührt; „Wiegen …“ öffnet das Panel
- Antwort trägt den Rest als geschätzt ein, aber nur wenn noch keiner erfasst ist; Mitteilung wird danach
  auf allen Geräten entfernt – ebenso, wenn der Rest in der App erfasst oder die Mahlzeit zurückgenommen wird
- Empfänger über Option `notify_services` (Vorgabe: zwei Handys)
- Keine Erinnerung für Mahlzeiten älter als 12 Stunden
- Antworten über die HA-WebSocket-API (Ereignis mobile_app_notification_action), Verbindung mit Ping
- Migration 8: Zeitpunkt der Erinnerung je Mahlzeit
- Neue Abhängigkeit: websocket-client 1.9.2 (reines Python)

## 0.12.0 – 2026-10-25

- Sensoren per MQTT-Discovery (Gerät „Katzenfutter <Name>“): kcal heute, kcal verbleibend, Tagesbedarf,
  Futter gefressen heute, Snacks heute, letzte Mahlzeit, offene Reste, Gewicht, Wasser aus Futter heute,
  Bestand Packungen (je Sorte als Attribut); binär: keine Futteraufnahme 24 h, Tierarzt-Hinweis
  (Texte als Attribut), Snack-Limit Kinder erreicht
- Aktualisierung sofort nach jeder Erfassung und jede Minute; Verfügbarkeit über katzenfutter/status
- Broker-Zugang automatisch vom Supervisor (`services: mqtt:need`), ersatzweise über Optionen
  mqtt_host, mqtt_port, mqtt_user, mqtt_password
- Webserver mit einem Prozess und 4 Threads (genau eine MQTT-Verbindung)
- Neue Abhängigkeit: paho-mqtt 2.1.0 (reines Python)

## 0.11.0 – 2026-10-25

- Heute-Ansicht als Startseite: Energie-Bilanz (Tagesbedarf, gefressen, Snacks, angeboten mit offenem Rest,
  verbleibend) mit Balken und Zahlen, Vorschlag der verbleibenden Menge in g und Packungen
- Futter und Wasser aus dem Futter gegen Richtwert; Getrunkenes „unbekannt“ bis PetKit
- Hinweis „Seit mehr als 24 Stunden keine Futteraufnahme“; Mahlzeiten mit offenem Rest lösen ihn nicht aus
- Gesundheits- und Snack-Hinweise sowie heutige Ereignisse auf der Startseite
- Geschätzte Werte mit „≈“ und kursiv gekennzeichnet

## 0.10.0 – 2026-10-25

- Gesundheit (Tab Füttern → „Erbrechen, Durchfall … melden“): Erbrechen, Haarballen, Durchfall,
  weicher Kot mit zwei Tipps; optional Uhrzeit, Person, Blut, Apathie, Notiz, Foto
- Automatische Zuordnung zur letzten Mahlzeit innerhalb von 12 Stunden (Haarballen nicht)
- Tierarzt-Hinweise: Blut, Apathie, ≥ 2× Erbrechen in 24 h, Durchfall länger als 48 h,
  nichts gefressen in 24 h trotz erfasster Reste
- Hinweise: ≥ 2 Ereignisse in 7 Tagen (ohne Haarballen), Ereignisse nach ≥ 2 Mahlzeiten mit
  demselben Hauptprotein (30 Tage); ausdrücklich keine Diagnosen
- Fotos unter /data/fotos (Teil des Backups), Auslieferung nur für selbst vergebene Dateinamen
- Löschen eines Eintrags bis 30 Minuten
- Migration 7: Blut, Apathie, Erfassungszeit und erfasst von je Ereignis

## 0.9.0 – 2026-10-25

- Einstellungen (Tab Katze → Einstellungen): Haushalt mit Personen, Rolle (Erwachsener/Kind) und
  optionalem HA-Benutzernamen; Snack-Limit für alle Kinder zusammen (Stück pro Tag)
- Einstellungen ändern nur Erwachsene, sobald Personen angelegt sind; Selbst-Aussperren wird verhindert
- Snacks (Tab Füttern → „Snack geben“): Stück oder Gramm, kcal aus Stückgewicht und kcal/100 g,
  Tagesstand mit Obergrenze 10 % des Tagesbedarfs, Stand der Kinder gegen das Limit
- Limit erreicht: Snack wird trotzdem gespeichert und deutlich markiert (Kalorienbilanz bleibt vollständig)
- „Gefüttert von“ / „Gegeben von“ wählbar (vorbelegt mit dem angemeldeten Benutzer); zusätzlich wird
  gespeichert, wer eingetragen hat
- Rechner zieht die Snack-kcal des Tages vom Hauptfutter ab
- Snack rückgängig bis 30 Minuten
- Migration 6: erfasst_von für Mahlzeit und Snack, Erfassungszeit für Snacks

## 0.8.0 – 2026-10-25

- Rest erfassen: Karte „Rest eintragen“ im Tab Füttern mit offenen Mahlzeiten der letzten 48 Stunden,
  Schätzstufen mit einem Tipp (Nichts 0 %, Wenig 10 %, Hälfte 50 %, Viel 75 %, Unberührt 100 %)
- Detailseite: Rest gewogen (g, ohne Napf), „verweigert“ getrennt von „unberührt“, Korrektur möglich
- Gefressene Menge und kcal werden berechnet; ohne kcal des Futters bleiben die kcal leer
- Liste „Heute“: geschätzte Werte mit „≈“ und „geschätzt“, gewogene mit „gewogen“, offene als „Rest offen“

## 0.7.0 – 2026-10-25

- Tab Füttern: Sorte wählen (angebrochene Packung zuerst, dann zuletzt gefüttert), Menge per
  Schnellwahl (Rest angebrochen, ½ Packung, 1 Packung) oder in g, Uhrzeit optional
- Person aus dem HA-Benutzer; Liste „Heute“ (Tagesgrenze Europe/Berlin)
- Bestand wird fortgeschrieben: erst angebrochene Packung, dann neue Packungen; Hinweis bei zu niedrigem Bestand
- Rückgängig für die letzte Mahlzeit einer Sorte (bis 30 Minuten), Bestand wird wiederhergestellt
- Barcode-Scan aus dem Tab Füttern wählt die Sorte direkt
- Migration 5: Bestandsbewegung und Erfassungszeit je Mahlzeit
- Zahlen kaufmännisch gerundet, Gramm mit Nachkomma wo nötig
- Neue Abhängigkeit: tzdata 2026.4 (Zeitzonendaten, reines Python)

## 0.6.1 – 2026-10-25

- Neues Futter: „Werte übernehmen von“ eine vorhandene Sorte (Marke, Linie, Futterart, Packung,
  Deklaration, kcal, Eigenschaften); Sorte, EAN, Bestand und Status werden nicht übernommen
- Funktioniert auch nach dem Scan, die gescannte EAN bleibt erhalten

## 0.6.0 – 2026-10-25

- Barcode-Erfassung (Tab Futter → „Barcode scannen“): Live-Kamera (nur HTTPS), Foto oder EAN-Eingabe
- Erkennung im Browser mit ZXing 0.23.0, als Datei im Add-on mitgeliefert (kein CDN, Apache-2.0)
- Foto-Erkennung versucht mehrere Bildgrößen und Hochformat (90°)
- Bekannte EAN öffnet das Futter, unbekannte legt ein neues Futter mit vorbelegter EAN an
- UPC-A und EAN-13 mit führender 0 gelten als gleich

## 0.5.0 – 2026-10-25

- Tab Futter: Futterdatenbank mit Liste, Anlegen und Bearbeiten
- kcal/100 g laut Hersteller oder aus vollständiger Deklaration berechnet (Kennzeichnung „berechnet“)
- Vergleich der aktiven Futter auf Trockenmasse (Protein, Fett, NfE, kcal)
- EAN-Prüfung (EAN-8, UPC-A, EAN-13 mit Prüfziffer), doppelte EAN wird abgelehnt
- Bestand: volle Packungen und angebrochene Menge
- Rechner im Tab Katze rechnet mit einem Futter aus der Datenbank
- Migration 4: Stückgewicht für Snacks
- Beschreibung des Add-ons aktualisiert

## 0.4.0 – 2026-10-25

- Oberfläche: Tabs Heute · Füttern · Futter · Verlauf · Katze (Heute, Füttern, Futter, Verlauf noch Platzhalter)
- Tab Katze: Profil mit Gewicht, Zielgewicht und BCS („offen“), Aktivitätsfaktor; Komma als Dezimaltrenner
- Jede Gewichtsänderung wird als manuelle Wiegung in der Historie gespeichert
- Rechner: RER, Tagesbedarf, Snack-Obergrenze, Wasser-Richtwert, Futtermenge in g und Packungen
- Technik-Test-Seite unter „Katze → Technik-Test“

## 0.3.0 – 2026-10-25

- Fachlogik als reine Funktionen (`fachlogik.py`): RER/MER mit Aktivitätsfaktor, Reduktion nur auf
  Zielgewicht, kcal/100 g nach Atwater (berechnet), Trockenmasse, Tagesmenge abzüglich Snacks,
  Packungsplan mit angebrochener Packung, Rest-Schätzstufen, Snack-Warnung ab 10 %, Wasserbilanz
- Noch keine Änderung an der Oberfläche

## 0.2.0 – 2026-10-25

- Datenbank-Fundament: versionierte Migrationen (Tabelle `schema_version`), Ausführung beim Start
  unter Schreibsperre
- Grundschema: katze, produkt, mahlzeit, snack, gewicht, ereignis, bestand, einstellung
- Erste Katze angelegt (Freigang, kastriert, Faktor 1,4; Gewicht, Zielgewicht und BCS offen)
- Testprotokoll aus 0.1.0 bleibt erhalten

## 0.1.0 – 2026-10-25

- Technik-Test: Ingress-Panel, HA-Benutzer aus Ingress, SQLite unter /data, HA-API über Supervisor,
  Test-Mitteilung mit Aktionen, Live-Kamera und Foto-Upload, Testprotokoll
