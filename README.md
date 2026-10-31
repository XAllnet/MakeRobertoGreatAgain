# MakeRobertoGreatAgain – Roberto Zones

## Version 0.5.0: local read-only world map diagnostics

Home Assistant custom integration for the Xiaomi Mi Robot Vacuum V1 (rockrobo.vacuum.v1). Runs inside Home Assistant Core without an additional VM, container or modified firmware.

**Experimental. No automatic navigation, no software-enforced no-go zones, no physical safety certification.** The existing manual short-step test services are unchanged.

### Install/update

Add https://github.com/XAllnet/MakeRobertoGreatAgain as a custom **Integration** repository in the Home Assistant 2026.11 Marketplace. Update Roberto Zones to 0.5.0 and restart Home Assistant.

### Position / charger

The Xiaomi Cloud Map Extractor v3 alpha exposes two diagnostic sensors, \`vacuum_position\` and \`charger_position\`, typically disabled in the entity registry. Enable them in Settings → Devices & services → Xiaomi Cloud Map Extractor → Entities. Roberto Zones auto-detects sensors associated with the **same map-extractor config entry** as your configured live image entity; if necessary set explicit \`position_entity\` and \`charger_entity\` under Roberto Zones Configure/Options.

Positions come from the *reported Xiaomi map* and are **not independently verified physical positions**. Null/unknown means no position fix.

### Reference/live overlay

The \`image\` entity **Referenz und Live-Karte** displays:
- A **side-by-side**, explicitly *unaligned*, comparison if the reference came from a historical Xiaomi app screenshot with no image-to-world calibration.
- A world-calibrated overlay when the reference and current map both have valid Xiaomi calibration points.

To create a world-calibrated reference, first let Roberto build a **complete map**. Then run \`roberto_zones.capture_reference\` from Settings → Tools → Actions. It saves original map bytes and matching \`calibration_points\` (with SHA256 binding) *locally* in \`/config/roberto_zones/\`. A historical screenshot can be uploaded with \`roberto_zones.import_reference\`, but that discards any prior calibration to prevent mismatched transforms.

Gray = saved reference, turquoise = freshly scanned floor; yellow = reported robot, green = reported dock. Overlap is a **visual plausibility indicator** and is never enough to authorize unattended travel. Image and sensor data originate from the same map extractor and do not independently confirm absolute physical location.

### Proving coordinates before navigation

The Xiaomi dock is approximately at (25500,25500) in native vacuum coordinates. First check the reported location when docked. Then manually test two widely separated safe checkpoints in different directions, verify the robot's **physical presence** there, and compare to the reported \`vacuum_position\` and transformed image pixels. If any source is missing, inconsistent, or stale, **fail closed**. No calculated target is sent by this version.

More detailed instructions: [README_DE.md](README_DE.md).

### Privacy and runtime

The reference image and calibration remain inside Home Assistant and are not part of this public GitHub repository. The integration only reacts to relevant state changes, throttles work, and uses Home Assistant's executor for image processing.
