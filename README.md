# MakeRobertoGreatAgain – Roberto Zones

**Version 0.1.1** · Home Assistant custom integration · read-only map diagnostics

This project explores resource-efficient map alignment for the Xiaomi Mi Robot Vacuum V1 (`rockrobo.vacuum.v1`) in Home Assistant.

**Safety:** This version NEVER sends vacuum commands. It does not enforce No-Go zones. Map orientation is only a candidate, not a validated navigation coordinate transform. Do not use its output to authorize unattended cleaning.

## Install via Home Assistant Marketplace (2026.11 beta or later)

1. Open **Settings → Marketplace** in Home Assistant.
2. Use **Add custom repository / Add by link** and provide: https://github.com/XAllnet/MakeRobertoGreatAgain
3. Choose **Integration** and install **Roberto Zones**.
4. Restart Home Assistant Core.
5. Open **Settings → Devices & services → Add integration → Roberto Zones (Diagnose)**.
6. Set the live image entity (for example `image.wohnzimmer_roberto_blanko_live_map`) and your **local Xiaomi Miio** vacuum entity.

Until a reference is available the status is `referenz_fehlt`.
When a **complete** current map is available, run action `roberto_zones.capture_reference` to store a private reference at `/config/roberto_zones/reference.png`. The action replaces an existing reference. To analyze immediately, run `roberto_zones.analyze_now`.

The image is processed only on relevant map state changes while cleaning, with throttling and debounce; the integration has no polling timer. Map analysis runs in Home Assistant's executor.

## Updates

For this early version the Marketplace can install directly from the repository's default branch, even without a GitHub release. Later tagged releases can provide versioned update notifications. Home Assistant Core may need a restart after updating.

## Privacy

No apartment screenshots, cleaning history, coordinate lists, tokens or cloud credentials are committed. The private reference is created on the Home Assistant machine and remains outside the installed integration folder.

## Limitations

This is an experimental proof of concept tested for Python syntax and offline map matching, not yet validated on the user's Home Assistant VM. The original Xiaomi V1 resets its map during new whole-house cleaning sessions. Image rotation alone cannot verify the robot's navigation coordinate system. External software cannot guarantee the robot will avoid cables; dangerous areas require physical protection.

See [German notes](README_DE.md).

Licensed under the repository's GPL-3.0 license.
