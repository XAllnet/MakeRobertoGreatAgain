# Roberto Zones 0.6.0 – Manuelle, unabhängige Koordinatenprüfung

**Kein Roboterbefehl wurde hinzugefügt.** Roberto wird weiterhin über die bereits vorhandene Xiaomi Vacuum Map Card gesteuert. Diese Version speichert Kontrollpunkte und prüft Positionsmeldungen nach einem Kartenreset. Alle Daten bleiben in Home Assistant.

## Einmalige Vorbereitung auf einer vollständigen Karte

1. Am besten eine **vollständige Live-Karte** von Roberto erstellen lassen. Map-Extractor-Sensoren \`vacuum_position\` und \`charger_position\` aktivieren.
2. Die Aktion \`roberto_zones.capture_reference\` ausführen. Das ersetzt die frühere Referenz und sichert ihre Kalibrierung samt Dockposition. **Alle alten Referenzprüfpunkte werden gelöscht**, weil sie an eine andere Referenz gebunden wären.
3. Drei gut erreichbare, weit voneinander entfernte und **nicht auf einer Linie** liegende Orte auswählen, zum Beispiel \`wohnzimmer_mitte\`, \`flur_frei\`, \`kueche_frei\`. Physisch eindeutig wiedererkennbare Bodenstellen verwenden, nicht nur ähnliche Punkte in der Bildansicht.
4. Roberto mit der bestehenden Live-Karten-Pin-Steuerung zum ersten Ort schicken, vollständig anhalten lassen, 10 Sekunden auf die Map-Extractor-Position warten.
5. In Einstellungen → Werkzeuge → Aktionen \`roberto_zones.record_reference_point\` auswählen. Eindeutigen Namen eingeben, **physische Anwesenheit und Stillstand bestätigen** und einmal ausführen. Status \`referenz_messung_1_von_2\` bedeutet, dass eine erste Position gespeichert wurde.
6. Nach mindestens 8 Sekunden **und einem neuen Positionsbericht des Map Extractors** dieselbe Aktion mit demselben Namen erneut ausführen. Roberto darf sich zwischen den beiden Messungen höchstens 120 mm bewegen. Die Messung darf nicht älter als 45 Sekunden sein.
7. Mit zwei weiteren Orten wiederholen. Die Punkte werden ausschließlich lokal unter \`/config/roberto_zones/checkpoints.json\` gespeichert und mit dem Hash der Referenzkarte verknüpft.

## Nach einer neuen Kartierung

1. Neue Reinigungs-/Kartierungssitzung starten. Alte Fahrfreigaben werden gesperrt. Roberto Zones muss die Ausrichtung wieder als eindeutig erkennen und sowohl Referenz- als auch Live-Dockposition kennen.
2. \`roberto_zones.begin_verification\` aufrufen. Es wird **kein** Fahrbefehl verschickt.
3. Den ersten früheren Bodenpunkt über die **aktuelle Live-Karte** ansteuern. Am exakt gleichen physischen Ort anhalten lassen.
4. \`roberto_zones.verify_checkpoint\` mit dem gespeicherten Punktnamen zweimal ausführen, wiederum nach mindestens 8 Sekunden und mit neuem Positionsbericht. Vor jedem Klick Anwesenheit und Stillstand bestätigen.
5. Die beiden anderen Punkte ebenso testen. Bei mehr als 250 mm Abweichung wird die Prüfung gesperrt.

Unter Roberto Zones gibt es einen neuen Sensor **Koordinatenprüfung** mit den Referenzpunktnamen, gemessenen Abweichungen, Kalibrierdrehung, Prüfstatus und ggf. Sperrgrund.

## Was als bestanden gilt

- Referenz und aktuelle Karte besitzen passende **eigene** Xiaomi-Kalibrierungsdaten
- Der Referenz-Dockpunkt und Live-Dockpunkt liegen als echte Messungen vor; angenommene 25500/25500-Anker genügen nicht
- Eindeutige Rotation und genügend erkennbare Raumgeometrie
- Drei räumlich verteilte physisch vom Benutzer bestätigte Orte
- Für jeden Ort zwei neue, mindestens 8 Sekunden getrennte Sensorberichte mit maximal 120 mm Standortdrift
- Höchstens 250 mm Positionsabweichung gegenüber der gespeicherten Referenz

Nach Erfolg lautet der Status \`pruefpunkte_bestanden\`. **Das ist ausschließlich eine bestätigte Koordinatendiagnose für den beobachteten Kartierungsdurchlauf, keine automatische Fahrfreigabe.** Bei neuer Reinigung, Kartenwechsel, veränderter Rotation oder widersprüchlichem Ergebnis wird die Prüfung ungültig. Ein nicht erkennbarer Kartenreset kann ohne robuste Kartenkennung nicht immer automatisch festgestellt werden. Deshalb bleibt automatische Navigation vollständig deaktiviert.

## Wichtige Grenzen

Die Xiaomi-Positionsdaten kommen mit der beobachteten Cloud-/Map-Extractor-Verzögerung. Home Assistant kann die wirkliche Messzeit am Roboter nicht garantieren. Auch ein korrekt gemeldeter Ankunftspunkt sagt nichts über die Sicherheit der **Route** aus. Der Xiaomi V1 kann den gesamten Weg abweichend planen und seine Haupt- und Seitenbürsten mitlaufen lassen. Die sieben No-Go-Zonen sind nicht technisch erzwungen.

Bei fehlender Kalibrierung, veralteten Messdaten, unklarer Kartendrehung, nicht gefundenem Dock oder unzureichender Anzahl/Verteilung der Prüfpunkte bleibt der Status gesperrt.

## Deine bestehende Xiaomi Vacuum Map Card bleibt unverändert

\`\`\`yaml
type: custom:xiaomi-vacuum-map-card
title: Roberto Blanko
entity: vacuum.wohnzimmer_rockrobo_vacuum_v1
map_source:
  camera: image.wohnzimmer_roberto_blanko_live_map
calibration_source:
  camera: true
map_modes:
  - template: vacuum_clean_zone
\`\`\`

Ein zusätzlicher \`vacuum_goto\`-Kartenmodus kann verwendet werden, ist für Roberto Zones 0.6.0 selbst aber keine Voraussetzung.

Die Integration wurde bisher nur anhand synthetischer Offline-Daten getestet. Kein Test auf deiner Home-Assistant-VM und keine garantierte No-Go-Zonen-Funktion.
