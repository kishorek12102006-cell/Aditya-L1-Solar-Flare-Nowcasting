"""
================================================================================
  ADITYA-L1 SOLAR FLARE NOWCASTING ENGINE  —  beta_nowcaster.py
  Simulated real-time playback from ISRO PRADAN FITS files
  Algorithm A : Dynamic Rolling-Sigma Anomaly Detector
  Algorithm B : Cross-Payload Temporal Coincidence Cataloguer
================================================================================
"""

import os
import sys
import time
import logging
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from collections import deque

# ── Import loaders from the fixed pipeline ────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aditya_l1_pipeline_fixed import (
    load_solexs_flight_data,
    load_hel1os_flight_data,
    apply_gti_filter,
)

# =============================================================================
# CONFIGURATION  — edit paths and tuning knobs here
# =============================================================================
BASE_DIR = r"C:\Users\kishore\OneDrive\Desktop"

SOLEXS_GTI = os.path.join(
    BASE_DIR,
    r"AL1_SLX_L1_20260611_v1.0\AL1_SLX_L1_20260611_v1.0\SDD2",
    "AL1_SOLEXS_20260611_SDD2_L1.gti.gz",
)
SOLEXS_LC = os.path.join(
    BASE_DIR,
    r"AL1_SLX_L1_20260611_v1.0\AL1_SLX_L1_20260611_v1.0\SDD2",
    "AL1_SOLEXS_20260611_SDD2_L1.lc.gz",
)

HEL1OS_LC = r"D:\isro_data\2026\06\11\HLS_20260611_000006_43178sec_lev1_V111\cdte\lightcurve_cdte1.fits"

HEL1OS_GTI = r"D:\isro_data\2026\06\11\HLS_20260611_000006_43178sec_lev1_V111\aux\gticdte1.fits"

LOG_FILE = os.path.join(BASE_DIR, "nowcaster_flare_log.txt")

# ── Nowcaster tuning knobs
TICK_SECONDS     = 0.05    # wall-clock seconds per simulated second (0.05 = 20× speed)
WINDOW_SECONDS   = 600     # rolling baseline window  : 10 minutes of history
K_SIGMA          = 4.5     # detection threshold      : mean + K × σ
MIN_EVENT_SEC    = 10      # minimum flare duration to log (seconds)
MATCH_WINDOW_MIN = 5       # cross-payload coincidence window (minutes)
DISPLAY_SECONDS  = 300     # seconds of history shown in the live plot
PLOT_REFRESH     = 10      # redraw every N ticks



# LOGGING SETUP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("NowcasterEngine")



# ALGORITHM A — DYNAMIC ROLLING-SIGMA ANOMALY DETECTOR

class NowcastState:
    """
    Maintains a fixed-length rolling window of recent photon counts and
    computes a dynamic detection threshold on every new tick.

    Threshold = rolling_mean + K × rolling_std

    This automatically tracks instrument aging and background orbital
    variations, keeping FAR very low while staying sensitive across A–X.
    """

    def __init__(self, name: str, window_sec: int = WINDOW_SECONDS, k: float = K_SIGMA):
        self.name       = name
        self.window_sec = window_sec
        self.k          = k

        self.times  = deque(maxlen=window_sec)
        self.counts = deque(maxlen=window_sec)

        self.mean      = 0.0
        self.std       = 0.0
        self.threshold = 0.0

        self.in_event        = False
        self.event_start     = None
        self.event_peak      = 0.0
        self.event_peak_time = None

    def push(self, timestamp: pd.Timestamp, count: float) -> dict | None:
        """
        Ingest one data point.
        Returns a completed event dict when an event ends, else None.
        """
        self.times.append(timestamp)
        self.counts.append(count)

        arr            = np.array(self.counts)
        self.mean      = float(arr.mean())
        self.std       = float(arr.std()) if len(arr) > 1 else 0.0
        self.threshold = self.mean + self.k * self.std

        is_above        = count > self.threshold
        completed_event = None

        if is_above and not self.in_event:
            self.in_event        = True
            self.event_start     = timestamp
            self.event_peak      = count
            self.event_peak_time = timestamp

        elif is_above and self.in_event:
            if count > self.event_peak:
                self.event_peak      = count
                self.event_peak_time = timestamp

        elif not is_above and self.in_event:
            duration = (timestamp - self.event_start).total_seconds()
            if duration >= MIN_EVENT_SEC:
                completed_event = {
                    "instrument":  self.name,
                    "start_time":  self.event_start,
                    "end_time":    timestamp,
                    "peak_time":   self.event_peak_time,
                    "peak_counts": self.event_peak,
                    "duration_s":  duration,
                }
            self.in_event        = False
            self.event_start     = None
            self.event_peak      = 0.0
            self.event_peak_time = None

        return completed_event


# =============================================================================
# ALGORITHM B — CROSS-PAYLOAD TEMPORAL COINCIDENCE CATALOGUER
# =============================================================================
class CoincidenceMatcher:
    """
    Streaming Algorithm B.
    Completed events from either instrument are submitted here.
    If a matching event from the other instrument arrives within
    MATCH_WINDOW_MIN minutes, the two merge into one catalogue entry.
    """

    def __init__(self, window_min: int = MATCH_WINDOW_MIN):
        self.window    = pd.Timedelta(minutes=window_min)
        self.solexs_q  = deque()
        self.hel1os_q  = deque()
        self.catalogue = []
        self.counter   = 1

    def submit(self, event: dict) -> dict | None:
        now        = event["end_time"]
        instrument = event["instrument"]

        if instrument == "SoLEXS":
            self._prune(self.hel1os_q, now)
            for h_ev in self.hel1os_q:
                if self._overlap(event, h_ev):
                    return self._make_entry(event, h_ev)
            self.solexs_q.append(event)

        elif instrument == "HEL1OS":
            self._prune(self.solexs_q, now)
            for s_ev in self.solexs_q:
                if self._overlap(s_ev, event):
                    return self._make_entry(s_ev, event)
            self.hel1os_q.append(event)

        return None

    def _prune(self, q: deque, reference_time: pd.Timestamp):
        while q and (reference_time - q[0]["end_time"]) > self.window:
            q.popleft()

    def _overlap(self, s_ev: dict, h_ev: dict) -> bool:
        delta = abs((s_ev["start_time"] - h_ev["start_time"]).total_seconds())
        return delta <= self.window.total_seconds()

    def _make_entry(self, s_ev: dict, h_ev: dict) -> dict:
        lag = (s_ev["peak_time"] - h_ev["peak_time"]).total_seconds()
        entry = {
            "Event_ID":           f"NOWCAST_ADITYA_{self.counter:03d}",
            "Start_Time":         min(s_ev["start_time"], h_ev["start_time"]),
            "SoLEXS_Peak_Time":   s_ev["peak_time"],
            "HEL1OS_Peak_Time":   h_ev["peak_time"],
            "SoLEXS_Peak_Counts": s_ev["peak_counts"],
            "HEL1OS_Peak_Counts": h_ev["peak_counts"],
            "Physics_Lag_Sec":    lag,
            "Flare_Class":        _estimate_class(s_ev["peak_counts"]),
        }
        self.catalogue.append(entry)
        self.counter += 1
        return entry


def _estimate_class(solexs_peak_counts: float) -> str:
    if   solexs_peak_counts > 50_000: return "X"
    elif solexs_peak_counts > 10_000: return "M"
    elif solexs_peak_counts > 2_000:  return "C"
    elif solexs_peak_counts > 500:    return "B"
    else:                              return "A"


# =============================================================================
# LIVE MATPLOTLIB PLOT
# =============================================================================
class LivePlot:
    """
    Two-panel real-time display.
    Compatible with matplotlib >= 3.4 (sharex via add_subplot, not join()).
    """

    COLORS = {
        "SoLEXS":    "#00BFFF",
        "HEL1OS":    "#FF6B35",
        "threshold": "#FFD700",
        "event":     "#FF4444",
        "match":     "#ADFF2F",
        "bg":        "#0D0D1A",
        "panel":     "#12122A",
        "text":      "#E0E0E0",
    }

    def __init__(self):
        plt.ion()
        self.fig = plt.figure(figsize=(15, 8), facecolor=self.COLORS["bg"])
        try:
            self.fig.canvas.manager.set_window_title(
                "Aditya-L1 Solar Flare Nowcasting Engine — LIVE"
            )
        except Exception:
            pass  # headless / non-interactive backend

        gs = gridspec.GridSpec(
            3, 1, figure=self.fig,
            height_ratios=[5, 5, 1],
            hspace=0.08,
        )

        # ── Use sharex= kwarg instead of the removed .join() API ──────────
        self.ax_s  = self.fig.add_subplot(gs[0])
        self.ax_h  = self.fig.add_subplot(gs[1], sharex=self.ax_s)   # ← fixed
        self.ax_st = self.fig.add_subplot(gs[2])

        for ax in (self.ax_s, self.ax_h, self.ax_st):
            ax.set_facecolor(self.COLORS["panel"])
            for spine in ax.spines.values():
                spine.set_color("#333355")

        self.ax_st.axis("off")
        # Hide x-tick labels on the top panel (shared axis handles bottom)
        plt.setp(self.ax_s.get_xticklabels(), visible=False)

        self._style_axis(self.ax_s, "SoLEXS  (Soft X-ray  2–22 keV)",  self.COLORS["SoLEXS"])
        self._style_axis(self.ax_h, "HEL1OS  (Hard X-ray  8–70 keV)", self.COLORS["HEL1OS"])

        plt.tight_layout(pad=1.2)

    def _style_axis(self, ax, title: str, color: str):
        ax.set_ylabel("Counts / sec", color=self.COLORS["text"], fontsize=9)
        ax.set_title(title, color=color, fontsize=10, fontweight="bold", loc="left", pad=4)
        ax.tick_params(colors=self.COLORS["text"], labelsize=8)
        ax.yaxis.label.set_color(self.COLORS["text"])
        ax.set_yscale("log")
        ax.grid(True, color="#222244", linewidth=0.5, linestyle="--")

    def _draw_panel(self, ax, title, color, times, counts, thresh, in_event, catalogue):
        ax.cla()
        self._style_axis(ax, title, color)
        if times:
            ax.plot(times, counts, color=color, lw=0.9, alpha=0.9, label="Count rate")
            ax.plot(
                times, thresh,
                color=self.COLORS["threshold"], lw=1.0,
                linestyle="--", alpha=0.7, label=f"Threshold (k={K_SIGMA}σ)",
            )
            if in_event:
                ax.axvspan(
                    times[-1], times[-1],
                    color=self.COLORS["event"], alpha=0.25, label="Active event",
                )
        for entry in catalogue[-10:]:
            ax.axvline(
                entry["SoLEXS_Peak_Time"],
                color=self.COLORS["match"], lw=1.2, linestyle=":", alpha=0.6,
            )
        ax.legend(
            loc="upper left", fontsize=7,
            facecolor="#1A1A3A", edgecolor="#333355",
            labelcolor=self.COLORS["text"],
        )

    def update(
        self,
        times_s, counts_s, thresh_s, in_event_s,
        times_h, counts_h, thresh_h, in_event_h,
        catalogue: list,
        sim_time: pd.Timestamp,
    ):
        self._draw_panel(
            self.ax_s,
            "SoLEXS  (Soft X-ray  2–22 keV)", self.COLORS["SoLEXS"],
            times_s, counts_s, thresh_s, in_event_s, catalogue,
        )
        self._draw_panel(
            self.ax_h,
            "HEL1OS  (Hard X-ray  8–70 keV)", self.COLORS["HEL1OS"],
            times_h, counts_h, thresh_h, in_event_h, catalogue,
        )

        self.ax_st.cla()
        self.ax_st.axis("off")
        n_events   = len(catalogue)
        last_class = catalogue[-1]["Flare_Class"]        if catalogue else "—"
        lag_str    = f"{catalogue[-1]['Physics_Lag_Sec']:+.0f}s" if catalogue else "—"
        flare_icon = "FLARE ACTIVE" if (in_event_s or in_event_h) else "QUIET SUN"

        status = (
            f"SIM TIME: {sim_time.strftime('%Y-%m-%d %H:%M:%S UTC')}    "
            f"{flare_icon}    "
            f"CATALOGUE EVENTS: {n_events}    "
            f"LAST CLASS: {last_class}    "
            f"NEUPERT LAG: {lag_str}"
        )
        self.ax_st.text(
            0.5, 0.5, status,
            transform=self.ax_st.transAxes,
            ha="center", va="center",
            fontsize=9, color="#FFD700",
            fontfamily="monospace", fontweight="bold",
        )

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()


# =============================================================================
# DATA ALIGNMENT  — common 1-second UTC grid
# =============================================================================
def align_timelines(df_s: pd.DataFrame, df_h: pd.DataFrame) -> tuple:
    """
    Reindex both frames to a common 1-second UTC grid over their overlap.
    Gaps up to 5 seconds are forward-filled.
    Raises ValueError when there is no temporal overlap.
    """
    common_start = max(df_s.index.min(), df_h.index.min())
    common_end   = min(df_s.index.max(), df_h.index.max())

    if common_start >= common_end:
        raise ValueError(
            "SoLEXS and HEL1OS have no overlapping time range.\n"
            f"  SoLEXS : {df_s.index.min()} → {df_s.index.max()}\n"
            f"  HEL1OS : {df_h.index.min()} → {df_h.index.max()}"
        )

    grid = pd.date_range(start=common_start, end=common_end, freq="s")

    def _reindex(series):
        return (
            series
            .reindex(grid, method="nearest", tolerance=pd.Timedelta("5s"))
            .ffill(limit=5)
            .fillna(0)
        )

    s_aligned = _reindex(df_s["COUNTS"])
    h_aligned = _reindex(df_h["COUNTS"])

    overlap_hours = (common_end - common_start).total_seconds() / 3600
    log.info(
        f"Timeline overlap: {common_start} → {common_end}  "
        f"({overlap_hours:.2f} hrs, {len(grid):,} ticks)"
    )
    return s_aligned, h_aligned


# =============================================================================
# MAIN NOWCASTING LOOP
# =============================================================================
def run_nowcaster():
    log.info("=" * 70)
    log.info("  ADITYA-L1 SOLAR FLARE NOWCASTING ENGINE")
    log.info("  Simulated playback mode — 1 FITS second per tick")
    log.info("=" * 70)

    # ── 1. Load and filter data ───────────────────────────────────────────────
    log.info("\n[INIT] Loading SoLEXS telemetry...")
    raw_s, gti_s = load_solexs_flight_data(SOLEXS_GTI, SOLEXS_LC)

    log.info("[INIT] Loading HEL1OS telemetry...")
    raw_h, gti_h = load_hel1os_flight_data(
        HEL1OS_LC,
        gti_fits_path=HEL1OS_GTI if os.path.exists(HEL1OS_GTI) else None,
    )

    log.info("\n[INIT] Applying GTI filters...")
    clean_s = apply_gti_filter(raw_s, gti_s)
    clean_h = apply_gti_filter(raw_h, gti_h)

    # ── 2. Align to a common 1-second grid ───────────────────────────────────
    log.info("[INIT] Aligning timelines to common 1-second grid...")
    try:
        s_series, h_series = align_timelines(clean_s, clean_h)
    except ValueError as e:
        log.error(f"\n[FATAL] {e}")
        log.error(
            "\nHint: SoLEXS and HEL1OS timestamps do not overlap — likely a "
            "wrong MET epoch. Check the MJDREFI/MJDREFF values in both FITS "
            "headers and set MISSION_EPOCH in aditya_l1_pipeline_fixed.py."
        )
        return

    total_ticks = len(s_series)
    log.info(f"[INIT] Ready — {total_ticks:,} ticks to replay.\n")

    # ── 3. Initialise Algorithm A state machines ──────────────────────────────
    state_s = NowcastState("SoLEXS",  window_sec=WINDOW_SECONDS, k=K_SIGMA)
    state_h = NowcastState("HEL1OS",  window_sec=WINDOW_SECONDS, k=K_SIGMA)

    # ── 4. Initialise Algorithm B matcher ────────────────────────────────────
    matcher = CoincidenceMatcher(window_min=MATCH_WINDOW_MIN)

    # ── 5. Initialise live plot ───────────────────────────────────────────────
    plot = LivePlot()

    disp_times_s  = deque(maxlen=DISPLAY_SECONDS)
    disp_counts_s = deque(maxlen=DISPLAY_SECONDS)
    disp_thresh_s = deque(maxlen=DISPLAY_SECONDS)
    disp_times_h  = deque(maxlen=DISPLAY_SECONDS)
    disp_counts_h = deque(maxlen=DISPLAY_SECONDS)
    disp_thresh_h = deque(maxlen=DISPLAY_SECONDS)

    log.info("[NOWCASTER] Playback started.\n")

    # ── 6. Main tick loop ─────────────────────────────────────────────────────
    try:
        for tick, (sim_time, (s_count, h_count)) in enumerate(
            zip(s_series.index, zip(s_series.values, h_series.values))
        ):
            s_ev = state_s.push(sim_time, float(s_count))
            disp_times_s.append(sim_time)
            disp_counts_s.append(max(float(s_count), 0.1))
            disp_thresh_s.append(max(state_s.threshold, 0.1))

            h_ev = state_h.push(sim_time, float(h_count))
            disp_times_h.append(sim_time)
            disp_counts_h.append(max(float(h_count), 0.1))
            disp_thresh_h.append(max(state_h.threshold, 0.1))

            for ev in filter(None, [s_ev, h_ev]):
                log.info(
                    f"EVENT DETECTED | {ev['instrument']:8s} | "
                    f"Start: {ev['start_time'].strftime('%H:%M:%S')} | "
                    f"Peak: {ev['peak_counts']:>10,.1f} cts/s | "
                    f"Duration: {ev['duration_s']:.0f}s"
                )
                match = matcher.submit(ev)
                if match:
                    log.info(
                        f"CATALOGUE ENTRY | {match['Event_ID']} | "
                        f"Class: {match['Flare_Class']} | "
                        f"SoLEXS peak: {match['SoLEXS_Peak_Counts']:>10,.1f} | "
                        f"HEL1OS peak: {match['HEL1OS_Peak_Counts']:>10,.1f} | "
                        f"Neupert lag: {match['Physics_Lag_Sec']:+.0f}s"
                    )

            if tick % PLOT_REFRESH == 0:
                plot.update(
                    list(disp_times_s), list(disp_counts_s), list(disp_thresh_s),
                    state_s.in_event,
                    list(disp_times_h), list(disp_counts_h), list(disp_thresh_h),
                    state_h.in_event,
                    matcher.catalogue,
                    sim_time,
                )

            time.sleep(TICK_SECONDS)

    except KeyboardInterrupt:
        log.info("\n[NOWCASTER] Stopped by user.")

    # ── 7. Final catalogue dump ───────────────────────────────────────────────
    log.info("\n" + "=" * 70)
    log.info("  NOWCAST SESSION COMPLETE")
    log.info("=" * 70)

    if matcher.catalogue:
        df_cat = pd.DataFrame(matcher.catalogue)
        log.info(f"\n{df_cat.to_string(index=False)}")
        out_csv = os.path.join(BASE_DIR, "nowcast_catalogue.csv")
        df_cat.to_csv(out_csv, index=False)
        log.info(f"\nCatalogue saved -> {out_csv}")
    else:
        log.info("No cross-payload events detected in this session.")

    plt.ioff()
    plt.show()


# =============================================================================
if __name__ == "__main__":
    run_nowcaster()
