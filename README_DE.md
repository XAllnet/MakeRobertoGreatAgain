# Roberto Zones 0.6.1 – Stabile Kartenregistrierung

Version 0.6.1 korrigiert das **Umspringen einer unbestätigten Kartenrotation**.

## Hintergrund

Die bisherige Version zeigte immer die bestbewertete Drehung, auch wenn deren Punktzahl zu niedrig war oder die vier möglichen Ausrichtungen fast gleich abschnitten. So konnte eine zufällige Übereinstimmung für einen Moment als korrekt gedrehte Überlagerung erscheinen.

Der alte Algorithmus belohnte außerdem fehlerhafte Zuordnungen, wenn ein Teil der aktuellen Karte außerhalb des Referenzbildes abgeschnitten wurde: Die Bewertung teilte lediglich durch die verbliebenen sichtbaren Pixel. Der neue Score berücksichtigt die **gesamte aktuell erkannte Kartenmaske**, begrenzt das zulässige Abschneiden und verwendet eine engere Konturtoleranz. Ein zweiter Suchschritt verfeinert die geschätzte Verschiebung in 50-mm-Schritten; das erhöht den Diagnoseaufwand in Maßen, ohne fortlaufendes Polling.

## Verhalten ab 0.6.1

- Alle Vierteldrehungen (0/90/180/270°) werden weiterhin als Kandidaten bewertet.
- **Ist die Drehung unklar, erscheint keine gedrehte Überlagerung.** Stattdessen: Referenz und aktuelle Karte nebeneinander mit sichtbarem Warnhinweis.
- Ein plausibler Kandidat muss bei **mindestens drei unterschiedlichen Kartenmasken** dieselbe Rotation und einen ähnlichen Versatz (maximal 120 mm Änderung zwischen den Beobachtungen) liefern, ehe die Integration eine überlagerte Vorschau anzeigt.
- Wiederholte Analysen derselben Karte zählen **nicht** mehrfach.
- Widersprüchliche Drehungen, fragwürdige Scores oder ein Kartenreset löschen die temporäre visuelle Bestätigung.
- Die Diagnosesensoren zeigen \`instant_visual_candidate\`, \`temporal_visual_match\`, \`consecutive_distinct_map_observations\`, \`rotation_score\`, \`rotation_score_gap\`, \`relative_shift_candidate_mm\` und \`anchor_assumed\`.

**Drei ähnliche Bilder bedeuten noch keinen physisch korrekten Standort.** Alle automatischen Navigationsbefehle und alle No-Go-Zonen bleiben gesperrt. Die Kontrollpunkt-Prüfung aus 0.6.0 bleibt der notwendige unabhängige zweite Schritt. Die bereits beobachtete Verzögerung von ca. 10 Sekunden des Map Extractors besteht weiter.

## Installation

Home Assistant Marketplace → Roberto Zones → Release \`v0.6.1\` erneut herunterladen → Home Assistant Core neu starten. Die bestehende Karte und gespeicherte Kontrollpunkte bleiben erhalten.

Die unveränderte Live-Karten-Steuerung:

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

## Diagnose

Wenn die Überlagerung nebeneinander bleibt, liegt **kein Fehler im Kartenbild** vor: Roberto Zones hat noch keine robuste Zuordnung gefunden. Es kann erforderlich sein, zuerst weitere markante Wände zu kartieren. Es werden weiterhin **keine** neuen Steuerbefehle an Roberto gesendet.

Tests prüfen insbesondere wechselnde Kandidatendrehungen, identische statt neuer Quellbilder, ungültige Ladeanker und das Sperren nach einem Kartenreset. Dies wurde noch nicht auf deiner Home-Assistant-Installation getestet.
