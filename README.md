# MakeRobertoGreatAgain — Roberto Zones

## 0.6.0: operator-confirmed coordinate verification

This is an experimental Home Assistant custom integration for Xiaomi Mi Robot Vacuum V1. The map overlay and position sensors remain diagnostic. **No automatic robot navigation, no enforced no-go zones, and no new vacuum commands** were added in 0.6.0. The existing supervised manual-test services remain available.

### Installation

Install the latest tagged release from https://github.com/XAllnet/MakeRobertoGreatAgain through Home Assistant Marketplace. Restart Home Assistant Core.

### Workflow

1. Use a **complete native live map**, not an AI-drawn image or historical screenshot. Enable the Xiaomi Cloud Map Extractor's optional \`vacuum_position\` and \`charger_position\` sensors.
2. Run \`roberto_zones.capture_reference\`. This also resets any older landmark baseline because it is bound to the exact reference image hash.
3. On that same reference map, physically visit at least three well-separated, non-collinear landmarks using your **existing** live Xiaomi Vacuum Map Card. At each landmark, wait until stopped, run \`roberto_zones.record_reference_point\` with the unique name and physical confirmation. Repeat the same action at least 8 seconds later after a **new** position-source report. Names persist only in Home Assistant's private \`/config/roberto_zones/checkpoints.json\`.
4. After a **new map run**, first establish a unique, dock-anchored image registration. Run \`roberto_zones.begin_verification\`.
5. Visit the same physical landmarks using your existing live-map controls. At each point, run \`roberto_zones.verify_checkpoint\` twice (new report required) with an independent physical confirmation.
6. Read **Koordinatenprüfung** sensor, residuals and reasons. All three landmarks must match within 250 mm; sampled stationary position must drift <=120 mm and map source reports must be fresh.

On map reset, a changed image orientation, ambiguous map contours, unavailable dock calibration, stale coordinates, or a mismatch, results are invalidated or blocked. Source timestamps are Home Assistant update timestamps and may not reflect robot measurement latency.

A passed diagnostic **never** calls \`vacuum_goto\` and never permits unattended travel or software-enforced no-go zones. A correct destination does not prove a collision-free route.

See [README_DE.md](README_DE.md) for the complete German procedure and current dashboard card YAML.
