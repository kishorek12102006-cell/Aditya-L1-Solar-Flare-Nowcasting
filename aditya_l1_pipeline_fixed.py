"""
================================================================================
  ADITYA-L1 PIPELINE  —  aditya_l1_pipeline_fixed.py
  Data loaders for SoLEXS and HEL1OS FITS / gzip-FITS products.

  Fixes applied
  -------------
  1. met_to_utc()         — tz-naive origin + .tz_localize("UTC")
  2. GTI columns          — START/STOP, START_TIME/STOP_TIME, TSTART/TSTOP,
                            T_START/T_STOP, tstart/tstop (case-insensitive)
  3. HEL1OS time column   — MJD, ISOT, TIME, T all handled
  4. HEL1OS counts col    — CTR, COUNTS, COUNT_RATE, RATE, CTS all handled
  5. apply_gti_filter()   — per-instrument unit awareness:
                            MJD-indexed DFs compared in MJD;
                            MET-indexed DFs compared in MET seconds
  6. SoLEXS epoch         — reads MJDREFI/MJDREFF or TIMEZERO from header
                            to get the real reference epoch instead of
                            assuming 2016-01-01
================================================================================
"""

import os
import gzip
import logging
import numpy as np
import pandas as pd
from astropy.io import fits

log = logging.getLogger("NowcasterEngine")


# =============================================================================
# HELPERS
# =============================================================================

def _open_fits(path: str):
    """Open a plain or gzip-compressed FITS file. Returns astropy HDUList."""
    if path.endswith(".gz"):
        import io
        with gzip.open(path, "rb") as gz:
            data = gz.read()
        return fits.open(io.BytesIO(data))
    return fits.open(path)


def _find_column(names, *candidates) -> str | None:
    """Case-insensitive column lookup; first matching candidate wins."""
    upper = {n.upper(): n for n in names}
    for c in candidates:
        if c.upper() in upper:
            return upper[c.upper()]
    return None


def _gti_to_intervals(gti_hdu_data) -> list:
    """
    Extract (start, stop) float pairs from a GTI binary table.
    Accepts START/STOP, START_TIME/STOP_TIME, TSTART/TSTOP, T_START/T_STOP
    (all case-insensitive).  Returns [] when columns cannot be found.
    """
    cols = gti_hdu_data.names
    log.info(f"[GTI] Available columns: {cols}")

    start_col = _find_column(cols, "START", "START_TIME", "TSTART", "T_START")
    stop_col  = _find_column(cols, "STOP",  "STOP_TIME",  "TSTOP",  "T_STOP")

    if start_col is None or stop_col is None:
        log.warning(f"[GTI] Cannot identify START/STOP in {cols} — filter skipped.")
        return []

    starts = np.array(gti_hdu_data[start_col], dtype="float64")
    stops  = np.array(gti_hdu_data[stop_col],  dtype="float64")
    log.info(f"[GTI] Loaded {len(starts)} intervals (cols: {start_col}/{stop_col})")
    return list(zip(starts, stops))


def _time_col(hdu_data) -> str:
    names = hdu_data.names
    col = _find_column(names, "TIME", "TIME_ADJ", "T", "MJD", "ISOT")
    if col is None:
        raise KeyError(f"No TIME column found; available: {names}")
    return col


def _counts_col(hdu_data) -> str:
    names = hdu_data.names
    col = _find_column(names, "COUNTS", "COUNT_RATE", "RATE", "CTS", "CTR")
    if col is None:
        raise KeyError(f"No COUNTS column found; available: {names}")
    return col


# =============================================================================
# TIME CONVERSION UTILITIES
# =============================================================================

# MJD zero point — tz-naive for use as pandas origin
_MJD_ZERO_NAIVE = pd.Timestamp("1858-11-17 00:00:00")

# Fallback mission epoch if header provides nothing (tz-naive for pandas)
_FALLBACK_EPOCH_NAIVE = pd.Timestamp("2014-01-01 00:00:00")

# tz-aware version kept for GTI arithmetic on MET-indexed frames
MISSION_EPOCH = pd.Timestamp("2014-01-01 00:00:00", tz="UTC")


def _epoch_from_header(hdr) -> pd.Timestamp:
    """
    Extract the time reference epoch from a FITS header (tz-naive).
    Priority: MJDREFI+MJDREFF  →  TIMEZERO (MJD)  →  fallback 2014-01-01.
    """
    mjdrefi = hdr.get("MJDREFI", None)
    if mjdrefi is not None:
        mjd_ref = float(mjdrefi) + float(hdr.get("MJDREFF", 0.0))
        return _MJD_ZERO_NAIVE + pd.to_timedelta(mjd_ref * 86400, unit="s")

    timezero = hdr.get("TIMEZERO", None)
    if timezero is not None:
        # TIMEZERO is sometimes given as MJD
        return _MJD_ZERO_NAIVE + pd.to_timedelta(float(timezero) * 86400, unit="s")

    log.warning("[EPOCH] No MJDREFI/TIMEZERO in header — using fallback 2014-01-01")
    return _FALLBACK_EPOCH_NAIVE


def met_to_utc(met_seconds, epoch_naive: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    """
    Convert MET seconds (relative to epoch_naive) to a UTC DatetimeIndex.
    pandas requires origin to be tz-naive; UTC is applied via tz_localize.
    """
    origin = epoch_naive if epoch_naive is not None else _FALLBACK_EPOCH_NAIVE
    return (
        pd.to_datetime(met_seconds, unit="s", origin=origin)
        .tz_localize("UTC")
    )


def mjd_to_utc(mjd_values) -> pd.DatetimeIndex:
    """Convert absolute MJD floats (days since 1858-11-17) to UTC."""
    seconds = np.asarray(mjd_values, dtype="float64") * 86400.0
    return (
        pd.to_datetime(seconds, unit="s", origin=_MJD_ZERO_NAIVE)
        .tz_localize("UTC")
    )


def isot_to_utc(isot_values) -> pd.DatetimeIndex:
    """Convert ISO-8601 string timestamps to UTC."""
    return pd.to_datetime(isot_values, utc=True)


# =============================================================================
# SOLEXS LOADER
# =============================================================================

def load_solexs_flight_data(gti_path: str, lc_path: str) -> tuple:
    """
    Load SoLEXS Level-1 lightcurve + GTI from gzip-FITS files.

    Returns
    -------
    df   : DataFrame — UTC DatetimeIndex, column 'COUNTS'
    gtis : list of (start_sec, stop_sec) in the same unit as the GTI file
    """
    print("Parsing SoLEXS Flight Files:")
    print(f" -> LC:  {os.path.basename(lc_path)}")
    print(f" -> GTI: {os.path.basename(gti_path)}")

    with _open_fits(lc_path) as hdul:
        lc_ext = next(
            (i for i, h in enumerate(hdul)
             if i > 0 and hasattr(h, "columns") and len(h.columns) > 0),
            1,
        )
        lc_data   = hdul[lc_ext].data
        hdr       = hdul[lc_ext].header
        t_col     = _time_col(lc_data)
        cts_col   = _counts_col(lc_data)
        times_raw = np.array(lc_data[t_col],  dtype="float64")
        counts    = np.array(lc_data[cts_col], dtype="float64")

        # Determine the correct epoch from the header
        epoch_naive = _epoch_from_header(hdr)
        log.info(f"[SoLEXS] Reference epoch from header: {epoch_naive}")

    idx = met_to_utc(times_raw, epoch_naive)
    df  = pd.DataFrame({"COUNTS": counts}, index=idx)
    df  = df[~df.index.duplicated(keep="first")].sort_index()
    # Tag so the GTI filter knows which unit system to use
    df.attrs["time_unit"] = "met"
    df.attrs["epoch"]     = epoch_naive
    log.info(f"[SoLEXS] LC loaded: {len(df):,} rows | "
             f"{df.index.min()} → {df.index.max()}")

    gtis = []
    if os.path.exists(gti_path):
        with _open_fits(gti_path) as hdul:
            gtis = _gti_to_intervals(hdul[1].data)
    else:
        log.warning(f"[SoLEXS] GTI file not found: {gti_path}")

    return df, gtis


# =============================================================================
# HEL1OS LOADER
# =============================================================================

def load_hel1os_flight_data(
    lc_fits_path: str,
    gti_fits_path: str | None = None,
) -> tuple:
    """
    Load HEL1OS Level-1 lightcurve + optional GTI from plain FITS files.

    Time-column handling
    --------------------
    MJD  → absolute MJD floats   → mjd_to_utc()
    ISOT → ISO-8601 strings       → isot_to_utc()
    TIME / T → MET seconds        → met_to_utc() with header epoch

    Returns
    -------
    df   : DataFrame — UTC DatetimeIndex, column 'COUNTS'
    gtis : list of (start, stop) in same unit as GTI file (MJD floats here)
    """
    print("Parsing HEL1OS Flight Files:")
    print(f" -> Target: {os.path.basename(lc_fits_path)}")

    with fits.open(lc_fits_path) as hdul:
        lc_ext = next(
            (i for i, h in enumerate(hdul)
             if i > 0 and hasattr(h, "columns") and len(h.columns) > 0),
            1,
        )
        lc_data = hdul[lc_ext].data
        hdr     = hdul[lc_ext].header
        t_col   = _time_col(lc_data)
        cts_col = _counts_col(lc_data)
        counts  = np.array(lc_data[cts_col], dtype="float64")

        log.info(f"[HEL1OS] Time column: '{t_col}'  |  Counts column: '{cts_col}'")

        t_upper = t_col.upper()
        if t_upper == "MJD":
            mjd_vals = np.array(lc_data[t_col], dtype="float64")
            idx = mjd_to_utc(mjd_vals)
            time_unit = "mjd"
            log.info("[HEL1OS] Time format: absolute MJD → UTC")

        elif t_upper == "ISOT":
            idx = isot_to_utc(np.array(lc_data[t_col]))
            time_unit = "isot"
            log.info("[HEL1OS] Time format: ISOT strings → UTC")

        else:
            times_met   = np.array(lc_data[t_col], dtype="float64")
            epoch_naive = _epoch_from_header(hdr)
            idx = met_to_utc(times_met, epoch_naive)
            time_unit = "met"
            log.info(f"[HEL1OS] Time format: MET seconds (epoch {epoch_naive}) → UTC")

    df = pd.DataFrame({"COUNTS": counts}, index=idx)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df.attrs["time_unit"] = time_unit
    log.info(f"[HEL1OS] LC loaded: {len(df):,} rows | "
             f"{df.index.min()} → {df.index.max()}")

    gtis = []
    if gti_fits_path and os.path.exists(gti_fits_path):
        print(f" -> GTI: {os.path.basename(gti_fits_path)}")
        with fits.open(gti_fits_path) as hdul:
            gtis = _gti_to_intervals(hdul[1].data)
    elif gti_fits_path:
        log.warning(f"[HEL1OS] GTI file not found: {gti_fits_path} — skipping")

    return df, gtis


# =============================================================================
# GTI FILTER  —  unit-aware, shared by both instruments
# =============================================================================

def apply_gti_filter(df: pd.DataFrame, gtis: list) -> pd.DataFrame:
    """
    Keep only rows whose timestamps fall inside at least one GTI interval.
    If gtis is empty, returns df unchanged.

    Unit handling
    -------------
    Reads df.attrs["time_unit"]:
      "mjd"  → compares GTI values (MJD floats) directly to the index in MJD
      "met"  → compares GTI values (MET seconds) to index offset from epoch
      other  → falls back to MET comparison against MISSION_EPOCH
    """
    if not gtis:
        log.warning("[GTI] No intervals — returning unfiltered data.")
        return df

    time_unit = df.attrs.get("time_unit", "met")

    if time_unit == "mjd":
        # Convert UTC index back to MJD floats for comparison
        index_vals = (
            (df.index - _MJD_ZERO_NAIVE.tz_localize("UTC"))
            .total_seconds().values / 86400.0
        )
    else:
        # MET seconds relative to the epoch stored in attrs, else MISSION_EPOCH
        epoch = df.attrs.get("epoch", None)
        if epoch is not None:
            ref = epoch.tz_localize("UTC") if epoch.tzinfo is None else epoch
        else:
            ref = MISSION_EPOCH
        index_vals = (df.index - ref).total_seconds().values

    mask = np.zeros(len(df), dtype=bool)
    for (t_start, t_stop) in gtis:
        mask |= (index_vals >= t_start) & (index_vals <= t_stop)

    filtered = df[mask]
    pct = 100.0 * mask.sum() / max(len(mask), 1)
    log.info(f"[GTI] {mask.sum():,}/{len(mask):,} rows kept ({pct:.1f} % in GTI)")
    return filtered
