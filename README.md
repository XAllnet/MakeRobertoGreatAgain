# MakeRobertoGreatAgain — Roberto Zones 0.6.1

Experimental Home Assistant custom integration for Xiaomi Mi Robot Vacuum V1. **No automated navigation or software-enforced no-go zones.**

### 0.6.1: prevent unstable preview rotation

Previous versions could render a misleading rotated overlay even when the map similarity score was below the confidence threshold and the best and second-best 90-degree orientations were nearly tied. A clipped partial map could also get an artificially high match score.

The update scores overlap against the full live map mask, reduces edge-matching tolerance, penalizes cropping, and refines translations at 50 mm resolution around a bounded coarse estimate. When a candidate is ambiguous, reference and live maps are presented **side by side** instead of showing an unconfirmed rotation.

An overlay preview requires three **different map-mask images**, each yielding the same rotation and a similar translation while the dock anchor is known. Reanalysis of identical imagery does not count. Map reset or changing candidates clears this visual consensus. It is *not independent physical verification*.

Version 0.6.0's manual checkpoint recording/verification services remain available. No new movement commands were added. Xiaomi positions may be cloud-delayed; checkpoint verification is only meaningful after stationary, fresh reports and physical confirmation. Refer to [README_DE.md](README_DE.md).

Install a tagged release in the Home Assistant Marketplace and restart Home Assistant Core.
