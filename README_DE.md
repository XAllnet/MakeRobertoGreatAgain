# Roberto Zones 0.6.2 – Originalgeometrie statt Fahrspuren

Roberto Zones 0.6.2 wurde für den **Xiaomi Mi Robot Vacuum V1** und den vorhandenen **Xiaomi Cloud Map Extractor v3.0.0-alpha-24** entwickelt. Es wird weder eine weitere Cloud-Abfrage noch ein weiterer Container eingerichtet.

## Änderung gegenüber 0.6.1

Die bisherigen Versionen verglichen die fertig gerenderten Kartenbilder. Diese enthalten abhängig von der Konfiguration auch Robertos gefahrenen Weg, die Roboterposition, die Ladestation, Zielmarkierungen oder gereinigte Flächen. Das kann die Kartenregistrierung verändern, obwohl die gemessene Raumgeometrie gleich bleibt.

0.6.2 liest stattdessen die **bereits im Map-Extractor-Koordinator zwischengespeicherte \`MapData.image.data\`-Ebene**. Diese wird durch den Roborock-Kartenparser aus den Wänden und Bodenpixeln erstellt, bevor Fahrweg und dynamische Symbole auf das Bild gezeichnet werden. Darauf berechnet Roberto Zones:

- eine geometrische Maske mit **eigenen, originalgetreuen Kalibrierungspunkten**;
- den Vergleich über 0°/90°/180°/270° und begrenzte Verschiebungen;
- den Stabilitäts-Fingerprint ausschließlich über die native Raumgeometrie.

Die Bildentität **„Referenz und Live-Karte“** zeigt die beiden reinen Geometrieebenen (oder nach stabiler Zuordnung die Überlagerung) statt der fertigen, dekorierten Live-Karte. Die vorhandene Xiaomi Vacuum Map Card bleibt vollständig erhalten und unverändert.

## Wichtig: Die Referenz einmal neu speichern

Frühere Referenzen enthalten nur die gerenderte Karte. Ein automatisches Entfernen der Fahrspuren aus diesen alten Bildern wäre unzuverlässig. Deshalb erkennt Roberto Zones die frühere Referenz und meldet **\`referenz_geometrie_fehlt\`**.

1. Roberto eine **vollständige, aktuelle Karte** erstellen lassen (kein kurzer Spot-Reinigungsbereich).
2. Die Aktion \`roberto_zones.capture_reference\` ausführen. **Achtung: Diese Aktion überschreibt die bisherige Referenz und setzt alte Kontrollpunkte zurück.** Falls du deren bisherige Daten behalten möchtest, vorher eine Home-Assistant-Sicherung anfertigen.
3. Roberto Zones speichert die originale Karte unter \`/config/roberto_zones/reference.png\` und zusätzlich die neue, fahrspurfreie Karte unter \`/config/roberto_zones/reference_geometry.png\`.
4. Kalibrierung, Dockposition und SHA256-Dateizuordnungen liegen lokal in \`/config/roberto_zones/reference_geometry.json\`.
5. Bei neuen Reinigungsläufen führt \`roberto_zones.analyze_now\` einen Vergleich gegen die native Live-Geometrie durch.

Eine historische Bilddatei ohne ursprüngliche Daten des Map Extractors bleibt weiterhin **nicht für die native Geometrie-Verifizierung geeignet**.

## Verhalten bei inkompatibler Map-Extractor-Version

Die neue geometrische Quelle ist eine **interne, nicht offiziell stabile Schnittstelle des Map Extractors 3 alpha**. Roberto Zones prüft deshalb ausdrücklich die Herkunft der Entität, ob die geparste Karte vorhanden ist und ob das Bild aus dem Koordinator **exakt** mit der gelesenen Home-Assistant-Live-Karte übereinstimmt.

Falls diese Bedingungen nicht zutreffen, erscheint \`native_geometrie_nicht_verfuegbar\`. Die Integration macht keine zusätzlichen Cloud-Abfragen, versucht keine unsichere Bildfarb-Heuristik und gibt keine Navigation frei.

## Diagnose

In **Kartenstatus** stehen:
- \`geometry_source: shared_map_extractor_native_cache\`
- \`geometry_only: true\`, \`no_path_fallback: true\`
- \`tracks_included: false\` und \`robot_marker_included: false\`
- \`live_mask_fingerprint\`, \`rotation_candidates\`, \`rotation_score_gap\`, \`temporal_visual_match\`

Eine höhere Ähnlichkeit oder eine stabile Ausrichtung ist **keine 100-%-Pixelidentität** und auch keine Bestätigung der realen Roboterposition. Die manuelle Koordinatenprüfung aus 0.6.0 bleibt nötig.

## Keine neuen Fahrbefehle

Automatische Navigation und No-Go-Zonen bleiben gesperrt. Insbesondere ist eine geometrisch richtige Referenz kein Nachweis dafür, dass Roberto die sieben geplanten Sperrzonen auf seiner selbst gewählten Route umfährt. Auch während Zielpunktfahrten können Bürsten laufen.

Die Installation erfordert nur das Marketplace-Release und einen Neustart von Home Assistant Core. Der verwendete Map Extractor wird **nicht** neu eingerichtet.

### Deine bestehende Live-Karten-Steuerung bleibt unverändert

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

Die neuen Funktionen wurden offline mit künstlichen Kartendaten getestet, aber noch nicht auf deinem Home Assistant mit realen Map-Extractor-Daten.
