# 🛰️ Aditya-L1 Solar Flare Nowcasting Engine

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-ISRO%20PRADAN-orange.svg)](https://www.isro.gov.in/)
[![Status](https://img.shields.io/badge/status-live%20beta-success.svg)]()

A real-time telemetry processing framework for space-based solar weather tracking. This engine ingests FITS flight data from the **Aditya-L1** satellite payloads to detect, classify, and cross-catalogue solar flare events instantly.

---

## 📊 Live Visualization Output

The real-time visualization engine splits data into high-contrast dual streams optimized for dark-room mission operations control (MOC) environments:

| Soft X-ray Payload (SoLEXS) | Hard X-ray Payload (HEL1OS) |
| :--- | :--- |
| **Energy Band:** 2–22 keV | **Energy Band:** 8–70 keV |
| Tracking plasma heating profiles | Tracking non-thermal particle acceleration |

### Execution Interface Profile
<img width="1918" height="1018" alt="image" src="https://github.com/user-attachments/assets/a0fb778b-cc00-48ad-b5b2-6ef589356a21" />

# Tuning knobs configuration
```text
TICK_SECONDS     = 0.05    # Wall-clock seconds per simulated second (20x replay speed)
WINDOW_SECONDS   = 600     # Rolling baseline history window size 
K_SIGMA          = 4.5     # Detection threshold multiplier
MIN_EVENT_SEC    = 10      # Minimum persistence time to filter noise transients
MATCH_WINDOW_MIN = 5       # Cross-payload temporal window limit
DISPLAY_SECONDS  = 300     # History span rendered on horizontal track
```
## terminal output 
```text
========= RESTART: C:\Users\kishore\OneDrive\Desktop\beta_nowcaster.py =========
2026-07-01 18:16:32,916  ======================================================================
2026-07-01 18:16:32,982    ADITYA-L1 SOLAR FLARE NOWCASTING ENGINE
2026-07-01 18:16:32,985    Simulated playback mode — 1 FITS second per tick
2026-07-01 18:16:32,986  ======================================================================
2026-07-01 18:16:32,989  
[INIT] Loading SoLEXS telemetry...
Parsing SoLEXS Flight Files:
 -> LC:  AL1_SOLEXS_20260611_SDD2_L1.lc.gz
 -> GTI: AL1_SOLEXS_20260611_SDD2_L1.gti.gz
2026-07-01 18:16:33,023  [SoLEXS] Reference epoch from header: 1970-01-01 00:00:00
2026-07-01 18:16:33,054  [SoLEXS] LC loaded: 86,400 rows | 2026-06-11 00:00:00+00:00 → 2026-06-11 23:59:59+00:00
2026-07-01 18:16:33,061  [GTI] Available columns: ['START', 'STOP']
2026-07-01 18:16:33,064  [GTI] Loaded 4 intervals (cols: START/STOP)
2026-07-01 18:16:33,067  [INIT] Loading HEL1OS telemetry...
Parsing HEL1OS Flight Files:
 -> Target: lightcurve_cdte1.fits
2026-07-01 18:16:33,081  [HEL1OS] Time column: 'MJD'  |  Counts column: 'CTR'
2026-07-01 18:16:33,095  [HEL1OS] Time format: absolute MJD → UTC
2026-07-01 18:16:33,101  [HEL1OS] LC loaded: 43,135 rows | 2026-06-11 00:00:07.098100662+00:00 → 2026-06-11 11:59:01.098100662+00:00
 -> GTI: gticdte1.fits
2026-07-01 18:16:33,110  [GTI] Available columns: ['tstart', 'tstop']
2026-07-01 18:16:33,113  [GTI] Loaded 1 intervals (cols: tstart/tstop)
2026-07-01 18:16:33,117  
[INIT] Applying GTI filters...
2026-07-01 18:16:33,126  [GTI] 86,396/86,400 rows kept (100.0 % in GTI)
2026-07-01 18:16:33,130  [GTI] 43,135/43,135 rows kept (100.0 % in GTI)
2026-07-01 18:16:33,133  [INIT] Aligning timelines to common 1-second grid...
2026-07-01 18:16:33,155  Timeline overlap: 2026-06-11 00:00:07.098100662+00:00 → 2026-06-11 11:59:01.098100662+00:00  (11.98 hrs, 43,135 ticks)
2026-07-01 18:16:33,159  [INIT] Ready — 43,135 ticks to replay.
```
