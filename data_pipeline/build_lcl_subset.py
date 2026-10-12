"""Build the Low Carbon London working subset that the notebook reads.

The London Datastore publishes the Low Carbon London smart meter readings (UK Power Networks) as
one CSV of half-hourly readings in kWh, and the 2013 time-of-use price signals as Tariffs.xlsx.
This script turns them into one row per household-day for a seeded sample of households:
`LCLid`, `tariff_group` (the data's `Std` or `ToU`), `date`, `price_signal` (none, high, low or
both for the time-of-use group, empty for the standard tariff group), then `r00` to `r47`, the
day's 48 half-hourly readings in GMT, rounded to three decimals (step 7).

Steps, each counted:
1. drop the "Null" readings and the rows stamped off the half-hour grid;
2. keep one of each exact duplicate (same household, time stamp and reading);
3. keep the chosen year;
4. find the households with every half-hourly reading of that year (or at most N missing), sorted
   by `LCLid`;
5. draw the sample: np.sort(np.random.default_rng(seed).choice(pool, size, replace=False));
6. take the SHA-256 of the sorted IDs joined by a newline, with no newline at the end;
7. round every reading in the sample to three decimals, to the nearest. The publisher's text holds
   some readings as float32 prints them, such as 1.4529999 for 1.453. The download is not changed.

Beside the subset it writes the price schedule, `lcl_2013_price_schedule.csv`: the tariff of each
GMT half-hour, High, Low or Normal, from Tariffs.xlsx, a separate file on the same London Datastore
page as the readings, moved to GMT. Where the move gives a half-hour two rows, which agree, one is
kept; a half-hour it leaves with none has no row.

The download is compressed with Deflate64, which Python's zipfile cannot open, so extract
`CC_LCL-FullData.csv` first with a tool that handles it, such as Info-ZIP unzip or 7-Zip. The
standard library and pandas are all it needs (NumPy comes with pandas); the xlsx is read with
zipfile and xml.etree.

    python data_pipeline/build_lcl_subset.py --lcl-csv CC_LCL-FullData.csv --tariffs Tariffs.xlsx

The defaults rebuild the submitted file and the price schedule byte for byte. --year,
--households, --seed and --pool adapt it. An at-most-N pool leaves empty readings that the notebook
does not fill, and the price signals exist for 2013 only, so in any other year `price_signal` is
empty.
"""

import argparse
import datetime as dt
import gzip
import hashlib
import platform
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent

DEFAULT_YEAR = 2013
DEFAULT_HOUSEHOLDS = 1000
DEFAULT_SEED = 42
DEFAULT_POOL = "strict"
DEFAULT_OUTPUT = "lcl_2013_1000_households.csv.gz"
DEFAULT_SCHEDULE = "lcl_2013_price_schedule.csv"

LCL_HEADER = ["LCLid", "stdorToU", "DateTime", "KWH/hh (per half hour) "]
TARIFF_HEADER = ("TariffDateTime", "Tariff")
TARIFF_LABELS = {"Normal", "High", "Low"}
HALF_HOUR = pd.Timedelta(minutes=30)
READING_COLUMNS = [f"r{i:02d}" for i in range(48)]

SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

SOURCE = {
    "Data set": "SmartMeter Energy Consumption Data in London Households",
    "Publisher": "UK Power Networks (Low Carbon London project), on the London Datastore",
    "Page": "https://data.london.gov.uk/dataset/smartmeter-energy-use-data-in-london-households",
    "Licence": "Creative Commons Attribution (CC BY 4.0), "
               "https://creativecommons.org/licenses/by/4.0/",
    "Readings file": "https://data.london.gov.uk/download/vqm0d/"
                     "3527bf39-d93e-4071-8451-df2ade1ea4f2/LCL-FullData.zip",
    "Tariff file": "https://data.london.gov.uk/download/vqm0d/"
                   "14855047-44c2-4856-8a48-e5649200e6ce/Tariffs.xlsx",
}


# --- arguments ----------------------------------------------------------------------------------

def parse_pool(text):
    """Return the most missing half-hourly readings a household may have: 0 for "strict", N for
    "at-most-N"."""
    if text == "strict":
        return 0
    match = re.fullmatch(r"at-most-(\d+)", text)
    if not match:
        raise ValueError(f'--pool must be "strict" or "at-most-N", not {text!r}')
    return int(match.group(1))


# --- the tariff file ----------------------------------------------------------------------------

def excel_serial_to_datetime(serial, date1904=False):
    """Convert an Excel serial date to a naive datetime, rounded to the second."""
    base = dt.datetime(1904, 1, 1) if date1904 else dt.datetime(1899, 12, 30)
    return base + dt.timedelta(seconds=round(float(serial) * 86400))


def read_tariffs(path):
    """Read Tariffs.xlsx with zipfile and xml.etree: one row per stamp, columns stamp and tariff,
    in the file's order and on the file's own clock."""
    with zipfile.ZipFile(path) as book:
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        shared = ET.fromstring(book.read("xl/sharedStrings.xml"))
        strings = ["".join(t.text or "" for t in si.iter(f"{{{SHEET_NS}}}t")) for si in shared]
        props = workbook.find(f"{{{SHEET_NS}}}workbookPr")
        date1904 = props is not None and props.get("date1904") in ("1", "true")
        first = workbook.find(f"{{{SHEET_NS}}}sheets/{{{SHEET_NS}}}sheet")
        rid = first.get(f"{{{REL_NS}}}id")
        target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        part = target.lstrip("/") if target.startswith("/") else "xl/" + target
        sheet = ET.fromstring(book.read(part))

    rows = []
    for row in sheet.iter(f"{{{SHEET_NS}}}row"):
        values = {}
        for cell in row.findall(f"{{{SHEET_NS}}}c"):
            value = cell.find(f"{{{SHEET_NS}}}v")
            if value is None:
                continue
            column = re.match(r"[A-Z]+", cell.get("r")).group()
            kind = cell.get("t")
            if kind == "s":
                values[column] = strings[int(value.text)]
            elif kind in (None, "n"):
                values[column] = float(value.text)
            else:
                raise ValueError(f"cell {cell.get('r')} has type {kind!r}, which this reader "
                                 "does not handle")
        rows.append(values)

    if not rows or (rows[0].get("A"), rows[0].get("B")) != TARIFF_HEADER:
        raise ValueError(f"{path} does not start with the header {TARIFF_HEADER}")
    stamps = [excel_serial_to_datetime(r["A"], date1904) for r in rows[1:]]
    return pd.DataFrame({"stamp": pd.to_datetime(stamps), "tariff": [r["B"] for r in rows[1:]]})


def bst_window(year):
    """British Summer Time in GMT: 01:00 GMT on the last Sunday of March to 01:00 GMT on the last
    Sunday of October."""
    def last_sunday(month):
        day = dt.date(year, month, 31)
        return day - dt.timedelta(days=(day.weekday() + 1) % 7)

    return (dt.datetime.combine(last_sunday(3), dt.time(1)),
            dt.datetime.combine(last_sunday(10), dt.time(1)))


def tariffs_to_gmt(tariffs):
    """Return a copy of the tariff rows with each stamp moved onto the readings' GMT clock.

    The tariff file appears to follow the UK local clock (inferred from when the time-of-use
    households change their use; neither file says so). A local stamp read as summer time is one
    hour ahead of GMT, so where that reading falls inside the year's British Summer Time window
    the stamp moves one hour back.
    """
    local = tariffs["stamp"]
    as_summer = local - pd.Timedelta(hours=1)
    inside = pd.Series(False, index=tariffs.index)
    for year in local.dt.year.unique():
        start, end = bst_window(int(year))
        inside |= (as_summer >= start) & (as_summer < end)
    moved = tariffs.copy()
    moved["stamp"] = local.where(~inside, as_summer)
    return moved


def signal_faults(tariffs_gmt):
    """List the GMT half-hours, from the first day the tariff rows cover to the last, that get two
    or more tariff rows or none: columns stamp, signals and tariffs (the values, joined)."""
    stamps = tariffs_gmt["stamp"]
    if stamps.empty:
        return pd.DataFrame(columns=["stamp", "signals", "tariffs"])
    grid = pd.date_range(stamps.min().normalize(),
                         stamps.max().normalize() + pd.Timedelta(days=1) - HALF_HOUR,
                         freq="30min")
    by_stamp = tariffs_gmt.groupby("stamp")["tariff"].agg(list)
    by_stamp.index = pd.DatetimeIndex(by_stamp.index).as_unit(grid.unit)
    lists = by_stamp.reindex(grid)
    faults = [(stamp, 0 if not isinstance(got, list) else len(got),
               "" if not isinstance(got, list) else ", ".join(got))
              for stamp, got in zip(grid, lists)
              if not isinstance(got, list) or len(got) != 1]
    return pd.DataFrame(faults, columns=["stamp", "signals", "tariffs"])


def day_price_signals(tariffs_gmt):
    """Label each GMT day the tariff rows cover, indexed by its ISO date: "both" when it holds a
    High and a Low signal, "high", "low", or "none"."""
    unknown = set(tariffs_gmt["tariff"]) - TARIFF_LABELS
    if unknown:
        raise ValueError(f"tariff values outside {sorted(TARIFF_LABELS)}: {sorted(unknown)}")
    day = tariffs_gmt["stamp"].dt.strftime("%Y-%m-%d")
    high = (tariffs_gmt["tariff"] == "High").groupby(day).any()
    low = (tariffs_gmt["tariff"] == "Low").groupby(day).any()
    label = np.select([high & low, high, low], ["both", "high", "low"], default="none")
    return pd.Series(label, index=high.index.rename(None), dtype=object)


def half_hour_schedule(tariffs_gmt):
    """The price schedule: one row per GMT half-hour the tariff rows cover, columns stamp and
    tariff, in time order. Where the move to GMT gives a half-hour two rows that agree, one is
    kept; two that differ stop the build, because no rule says which to keep. A half-hour the
    move leaves with no row is left out."""
    unknown = set(tariffs_gmt["tariff"]) - TARIFF_LABELS
    if unknown:
        raise ValueError(f"tariff values outside {sorted(TARIFF_LABELS)}: {sorted(unknown)}")
    kinds = tariffs_gmt.groupby("stamp")["tariff"].nunique()
    if (kinds > 1).any():
        raise ValueError(f"{int((kinds > 1).sum())} GMT half-hours carry different tariffs; no "
                         "rule says which to keep, so the build stops")
    one = tariffs_gmt.drop_duplicates("stamp").sort_values("stamp", kind="stable")
    return one[["stamp", "tariff"]].reset_index(drop=True)


# --- the readings -------------------------------------------------------------------------------

def read_lcl_csv(path, chunksize=10_000_000):
    """Read the published readings into one row per reading: LCLid, tariff_group, stamp, kwh.

    "Null" readings become NaN so step 1 can count them, and any other text that is not a number
    stops the read. Each reading is parsed to the nearest double, so nothing is rounded.
    """
    with open(path, newline="", encoding="ascii") as fh:
        header = fh.readline().rstrip("\r\n").split(",")
    if header != LCL_HEADER:
        raise ValueError(f"{path} has the header {header}, not {LCL_HEADER}")
    reader = pd.read_csv(path, header=0, names=["LCLid", "tariff_group", "stamp", "kwh"],
                         dtype={"LCLid": "category", "tariff_group": "category", "stamp": str,
                                "kwh": "float64"},
                         na_values={"kwh": ["Null"]}, keep_default_na=False,
                         float_precision="round_trip", chunksize=chunksize)
    parts = []
    for chunk in reader:
        chunk["stamp"] = pd.to_datetime(chunk["stamp"], format="%Y-%m-%d %H:%M:%S.%f")
        parts.append(chunk)
    union = pd.api.types.union_categoricals
    return pd.DataFrame({
        "LCLid": union([p["LCLid"] for p in parts]),
        "tariff_group": union([p["tariff_group"] for p in parts]),
        "stamp": pd.concat([p["stamp"] for p in parts], ignore_index=True),
        "kwh": np.concatenate([p["kwh"].to_numpy() for p in parts]),
    })


def drop_null_and_off_grid(readings):
    """Step 1: drop the "Null" readings and the rows stamped off the half-hour grid, counted."""
    null = readings["kwh"].isna()
    off_grid = readings["stamp"] != readings["stamp"].dt.floor("30min")
    drop = null | off_grid
    counts = {"rows_in": len(readings), "null_rows": int(null.sum()),
              "off_grid_rows": int(off_grid.sum()),
              "null_and_off_grid_rows": int((null & off_grid).sum()),
              "rows_dropped": int(drop.sum()), "rows_out": int((~drop).sum())}
    return readings[~drop].reset_index(drop=True), counts


def keep_one_of_each_duplicate(readings):
    """Step 2: keep the first of each exact duplicate (same household, time stamp and reading),
    counted. A household and time stamp with two different readings stops the build, because no
    rule says which to keep."""
    exact = readings.duplicated(subset=["LCLid", "stamp", "kwh"], keep="first")
    kept = readings[~exact]
    clash = kept.duplicated(subset=["LCLid", "stamp"], keep=False)
    if clash.any():
        pairs = len(kept.loc[clash, ["LCLid", "stamp"]].drop_duplicates())
        raise ValueError(f"{pairs} household and time stamp pairs carry different readings; "
                         "no cleaning rule covers that, so the build stops")
    counts = {"rows_in": len(readings), "exact_duplicate_rows": int(exact.sum()),
              "rows_out": len(kept)}
    return kept.reset_index(drop=True), counts


def keep_year(readings, year):
    """Step 3: keep the readings stamped inside the year, 1 Jan 00:00 to 31 Dec 23:30."""
    start, end = pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1)
    inside = (readings["stamp"] >= start) & (readings["stamp"] < end)
    return readings[inside].reset_index(drop=True)


def half_hours_in_year(year):
    """The number of half-hourly readings a complete household has in the year."""
    return (dt.date(year + 1, 1, 1) - dt.date(year, 1, 1)).days * 48


def complete_pool(year_readings, year, max_missing):
    """Step 4: the households, sorted by LCLid, missing at most max_missing of the year's
    half-hourly readings. Takes the output of keep_one_of_each_duplicate and keep_year."""
    counts = year_readings.groupby("LCLid", observed=True).size()
    missing = half_hours_in_year(year) - counts
    return np.sort(np.asarray(counts.index[missing <= max_missing].astype(str), dtype=str))


def draw_sample(pool, households, seed):
    """Step 5: draw the households without replacement from the pool sorted by LCLid, so the draw
    does not depend on the file's order, and return them sorted."""
    ordered = np.sort(np.asarray(pool, dtype=str))
    if households > len(ordered):
        raise ValueError(f"cannot draw {households} households from a pool of {len(ordered)}")
    return np.sort(np.random.default_rng(seed).choice(ordered, size=households, replace=False))


def sample_sha256(ids):
    """Step 6: the SHA-256 of the sorted IDs joined by a newline, with no newline at the end."""
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


# --- the output ---------------------------------------------------------------------------------

def household_days(year_readings, sample, year, signals):
    """One row per household-day for the sampled households, in LCLid then date order: LCLid,
    tariff_group, date, price_signal and r00 to r47. A missing reading is left empty, and the
    price signal is empty for the standard tariff group and on days the tariff rows do not cover.
    """
    ids = np.asarray(sample, dtype=str)
    days = half_hours_in_year(year) // 48
    start = pd.Timestamp(year, 1, 1)
    mine = year_readings[year_readings["LCLid"].isin(ids)]
    mine = mine[(mine["stamp"] >= start) & (mine["stamp"] < pd.Timestamp(year + 1, 1, 1))]

    codes, found = pd.factorize(mine["LCLid"])
    position = pd.Index(ids).get_indexer(np.asarray(found, dtype=str))
    values = np.full((len(ids), days * 48), np.nan)
    values[position[codes], ((mine["stamp"] - start) // HALF_HOUR).to_numpy()] = mine["kwh"]

    groups = mine.groupby("LCLid", observed=True)["tariff_group"].agg(["nunique", "first"])
    groups.index = groups.index.astype(str)
    if (groups["nunique"] != 1).any() or len(groups) != len(ids):
        raise ValueError("each sampled household needs one tariff group and at least one reading")
    group = groups["first"].astype(str).reindex(ids).to_numpy()

    dates = pd.date_range(start, periods=days, freq="D").strftime("%Y-%m-%d")
    day_signal = signals.reindex(dates).fillna("").to_numpy(dtype=object)
    price = np.where(np.repeat(group == "ToU", days), np.tile(day_signal, len(ids)), "")
    head = pd.DataFrame({"LCLid": np.repeat(ids, days), "tariff_group": np.repeat(group, days),
                         "date": np.tile(np.asarray(dates), len(ids)),
                         "price_signal": price.astype(object)})
    body = pd.DataFrame(values.reshape(-1, 48), columns=READING_COLUMNS)
    return pd.concat([head, body], axis=1)


def more_places(values, places=3):
    """True for each reading that rounding to `places` decimals would change; False for an empty
    one."""
    values = np.asarray(values, dtype=float)
    return ~np.isnan(values) & (np.round(values, places) != values)


def round_readings(subset, places=3):
    """Step 7: round every reading, r00 to r47, to `places` decimals, to the nearest, counted.

    To the nearest, not up, which would move every changed reading upward. A reading that already
    has three decimals keeps its exact value, and an empty reading stays empty. Returns the
    rounded copy and the count of readings that changed, with the largest change in kWh."""
    values = subset[READING_COLUMNS].to_numpy(dtype=float)
    rounded = np.round(values, places)
    changed = more_places(values, places)
    out = subset.copy()
    out[READING_COLUMNS] = rounded
    largest = float(np.abs(rounded - values)[changed].max()) if changed.any() else 0.0
    return out, {"readings_changed": int(changed.sum()), "largest_change": largest}


def file_sha256(path):
    """The SHA-256 of a file's bytes, read in blocks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_inside(path):
    """The size in bytes and the SHA-256 of the CSV text a .csv or .csv.gz file holds."""
    digest, size = hashlib.sha256(), 0
    opener = gzip.open if Path(path).suffix == ".gz" else open
    with opener(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def write_subset(subset, path):
    """Write the subset as CSV with Unix line ends, gzipped when the name ends in .gz, and return
    the SHA-256 of the CSV text. The gzip header holds a fixed time of 0 and the file's own name,
    so the same inputs rebuild it byte for byte."""
    path = Path(path)
    compression = {"method": "gzip", "mtime": 0} if path.suffix == ".gz" else None
    subset.to_csv(path, index=False, lineterminator="\n", compression=compression)
    return csv_inside(path)[1]


def write_schedule(schedule, path):
    """Write the price schedule as a plain CSV with Unix line ends, each stamp as
    YYYY-MM-DD HH:MM:SS, and return its SHA-256. The same tariff file rewrites it byte for byte."""
    text = schedule.assign(stamp=schedule["stamp"].dt.strftime("%Y-%m-%d %H:%M:%S"))
    text.to_csv(path, index=False, lineterminator="\n")
    return file_sha256(path)


# --- the manifest -------------------------------------------------------------------------------

PUBLISHER_FIGURES = {
    "zip": "764.54 MB",
    "csv": '"around 10GB when unzipped"',
    "rows": '"around 167million rows"',
    "households": '"a sample of 5,567 London Households"',
    "tariffs": "239.63 kB",
}


def file_row(label, size, digest):
    """One Files table row: label, bytes, MiB to two places, SHA-256."""
    return f"| {label} | {size:,} | {size / 2**20:,.2f} | `{digest}` |"


def manifest_text(s):
    """The MANIFEST.md text for a run's summary."""
    st, tf = s["steps"], s["tariffs"]
    out_name = Path(s["output"]).name
    lines = [
        "# Manifest: the Low Carbon London working subset",
        "",
        f"Written by `data_pipeline/build_lcl_subset.py` on {s['built']}, with Python "
        f"{s['python']}, pandas {s['pandas']} and NumPy {s['numpy']}. Year {s['year']}, "
        f"{s['households']:,} households, seed {s['seed']}, pool `{s['pool_rule']}`.",
        "",
        "## Source",
        "",
        "| Item | Value |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in SOURCE.items()]
    lines += [f"| Downloaded | {s['downloaded'] or 'not recorded on this run'} |", ""]

    lines += ["## Files", "", "| File | Bytes | MiB | SHA-256 |", "|---|---|---|---|"]
    if s["zip"]:
        lines.append(file_row(f"`{s['zip']['name']}` (the download)", s["zip"]["bytes"],
                              s["zip"]["sha256"]))
    lines.append(file_row(f"`{s['lcl_csv']['name']}` (extracted from the download)",
                          s["lcl_csv"]["bytes"], s["lcl_csv"]["sha256"]))
    lines.append(file_row(f"`{s['tariff_file']['name']}` (the download)",
                          s["tariff_file"]["bytes"], s["tariff_file"]["sha256"]))
    lines.append(file_row(f"`{out_name}` (the output)", s["output_bytes"], s["output_sha256"]))
    if out_name.endswith(".gz"):
        lines.append(file_row(f"`{out_name[:-3]}` (the CSV inside the gzip)",
                              s["output_csv_bytes"], s["output_csv_sha256"]))
    lines.append(file_row(f"`{s['schedule']['name']}` (the price schedule)",
                          s["schedule"]["bytes"], s["schedule"]["sha256"]))
    lines.append("")

    csv_bytes = s["lcl_csv"]["bytes"]
    lines += ["## The publisher's figures beside the measured ones", "",
              "| Figure | On the London Datastore page | Measured |", "|---|---|---|"]
    if s["zip"]:
        lines.append(f"| Download size | {PUBLISHER_FIGURES['zip']} | {s['zip']['bytes']:,} bytes,"
                     f" which is {s['zip']['bytes'] / 2**20:.2f} MiB |")
    lines += [
        f"| Unzipped size | {PUBLISHER_FIGURES['csv']} | {csv_bytes:,} bytes, which is "
        f"{csv_bytes / 2**30:.2f} GiB or {csv_bytes / 1e9:.2f} GB |",
        f"| Rows | {PUBLISHER_FIGURES['rows']} | {st['rows_read']:,} rows |",
        f"| Households | {PUBLISHER_FIGURES['households']} | {st['households_read']:,} household "
        "IDs |",
        f"| Tariff file size | {PUBLISHER_FIGURES['tariffs']} | {s['tariff_file']['bytes']:,} "
        f"bytes, which is {s['tariff_file']['bytes'] / 2**10:.2f} KiB |",
        "",
    ]

    lines += ["## Pipeline steps", "", "| Step | Count |", "|---|---|",
              f"| Rows read | {st['rows_read']:,} |",
              f"| Households read | {st['households_read']:,} |",
              f"| Step 1, \"Null\" readings | {st['null_rows']:,} |",
              f"| Step 1, rows off the half-hour grid | {st['off_grid_rows']:,} |",
              f"| Step 1, rows both \"Null\" and off the grid | {st['null_and_off_grid_rows']:,} |",
              f"| Step 1, rows dropped | {st['rows_dropped_step_1']:,} |",
              f"| Step 1, rows left | {st['rows_after_step_1']:,} |",
              f"| Step 2, exact duplicates dropped | {st['exact_duplicate_rows']:,} |",
              f"| Step 2, rows left | {st['rows_after_step_2']:,} |",
              f"| Step 3, rows in {s['year']} | {st['rows_in_year']:,} |",
              f"| Step 3, households with a reading in {s['year']} | "
              f"{st['households_in_year']:,} |",
              f"| Step 4, households in the pool | {s['pool']:,} |",
              f"| Step 4, pool, standard tariff group | {s['pool_std']:,} |",
              f"| Step 4, pool, time-of-use group | {s['pool_tou']:,} |",
              f"| Step 5, households drawn | {s['sample']:,} |",
              f"| Step 5, sample, standard tariff group | {s['sample_std']:,} |",
              f"| Step 5, sample, time-of-use group | {s['sample_tou']:,} |",
              f"| Step 5, first three IDs | {', '.join(s['first_ids'])} |",
              f"| Step 6, SHA-256 of the sorted IDs | `{s['sample_sha256']}` |",
              f"| Step 7, readings the rounding changed | {s['rounding']['readings_changed']:,} |",
              f"| Output rows | {s['output_rows']:,} |",
              f"| Output readings left empty | {s['missing_readings']:,} |",
              ""]

    first = s["download_first_over"]
    lines += ["## Rounding", "",
              "Some readings in the published text have more than three decimal places, such as "
              "the first of them below, which looks like a three-decimal reading stored as "
              "float32. Step 7 rounds every reading in the sample to three decimals, to the "
              "nearest, not up, which would move every changed reading upward. The download "
              "itself is kept unchanged, with its hash above.", "",
              "| Item | Value |", "|---|---|",
              f"| Readings in the download with more than three decimals | "
              f"{s['download_readings_over_three_places']:,} |",
              "| The first of them in the download | "
              + (f"{first['LCLid']}, {first['stamp']}, {first['kwh']!r} |" if first else "none |"),
              f"| Largest change in the sample, kWh | "
              f"{s['rounding']['largest_change']:.7f} |",
              ""]

    lines += ["## Price signals", "",
              "The tariff file appears to follow the UK local clock (inferred from when the "
              "time-of-use households change their use; neither file says so). Its stamps inside "
              "British Summer Time move one hour back to the readings' GMT stamps.", "",
              "| Item | Count |", "|---|---|",
              f"| Tariff rows | {tf['rows']:,} |",
              f"| High half-hours | {tf['high_half_hours']:,} |",
              f"| Low half-hours | {tf['low_half_hours']:,} |",
              f"| Days with a High signal, by the file's own dates | {tf['file_days_high']:,} |",
              f"| Days with a Low signal, by the file's own dates | {tf['file_days_low']:,} |",
              f"| Days with a High signal, GMT | {tf['gmt_days_high']:,} |",
              f"| Days with a Low signal, GMT | {tf['gmt_days_low']:,} |",
              f"| Days with both, GMT | {tf['gmt_days_both']:,} |",
              f"| Days with either, GMT | {tf['gmt_days_either']:,} |",
              f"| Half-hours in the price schedule | {s['schedule']['rows']:,} |",
              "",
              "GMT half-hours that get two tariff rows or none after the move:", "",
              "| GMT half-hour | Tariff rows | Values |", "|---|---|---|"]
    lines += [f"| {f['stamp']} | {f['signals']} | {f['tariffs'] or 'none'} |"
              for f in tf["faults"]] or ["| none | | |"]
    lines += ["",
              "The price schedule keeps one row for each half-hour above that gets two tariff "
              "rows, since the build stops unless they agree, and has no row for a half-hour that "
              "gets none.",
              ""]
    return "\n".join(lines)


# --- the run ------------------------------------------------------------------------------------

def describe(path):
    """Name, size in bytes and SHA-256 of an input file."""
    path = Path(path)
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def tariff_summary(tariffs, gmt, signals):
    """Counts for the manifest's price signal section."""
    file_day = tariffs["stamp"].dt.date
    return {"rows": len(tariffs),
            "high_half_hours": int((tariffs["tariff"] == "High").sum()),
            "low_half_hours": int((tariffs["tariff"] == "Low").sum()),
            "file_days_high": file_day[tariffs["tariff"] == "High"].nunique(),
            "file_days_low": file_day[tariffs["tariff"] == "Low"].nunique(),
            "gmt_days_high": int(signals.isin(["high", "both"]).sum()),
            "gmt_days_low": int(signals.isin(["low", "both"]).sum()),
            "gmt_days_both": int((signals == "both").sum()),
            "gmt_days_either": int((signals != "none").sum()),
            "faults": signal_faults(gmt).to_dict("records")}


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--lcl-csv", required=True, help="CC_LCL-FullData.csv, extracted")
    parser.add_argument("--tariffs", required=True, help="Tariffs.xlsx")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--households", type=int, default=DEFAULT_HOUSEHOLDS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--pool", default=DEFAULT_POOL, help='"strict" or "at-most-N"')
    parser.add_argument("--out", default=str(REPO / DEFAULT_OUTPUT),
                        help="a .csv or .csv.gz path (default: the submitted file); the price "
                        "schedule is written beside it")
    parser.add_argument("--manifest", help="also write the manifest here")
    parser.add_argument("--zip", help="the downloaded zip, hashed for the manifest")
    parser.add_argument("--downloaded", help="the download date, for the manifest")
    args = parser.parse_args(argv)
    if not (args.out.endswith(".csv") or args.out.endswith(".csv.gz")):
        parser.error("--out must end in .csv or .csv.gz")
    return args


def main(argv=None):
    """Build the subset, print the counts and return them; write the manifest if asked."""
    args = parse_args(argv)
    max_missing = parse_pool(args.pool)

    tariffs = read_tariffs(args.tariffs)
    gmt = tariffs_to_gmt(tariffs)
    signals = day_price_signals(gmt)
    schedule = half_hour_schedule(gmt)

    readings = read_lcl_csv(args.lcl_csv)
    steps = {"rows_read": len(readings), "households_read": readings["LCLid"].nunique()}
    over = np.flatnonzero(more_places(readings["kwh"].to_numpy()))
    first_over = None
    if over.size:
        row = readings.iloc[over[0]]
        first_over = {"LCLid": str(row["LCLid"]), "stamp": str(row["stamp"]),
                      "kwh": float(row["kwh"])}
    readings, c1 = drop_null_and_off_grid(readings)
    readings, c2 = keep_one_of_each_duplicate(readings)
    readings = keep_year(readings, args.year)
    steps.update({"null_rows": c1["null_rows"], "off_grid_rows": c1["off_grid_rows"],
                  "null_and_off_grid_rows": c1["null_and_off_grid_rows"],
                  "rows_dropped_step_1": c1["rows_dropped"], "rows_after_step_1": c1["rows_out"],
                  "exact_duplicate_rows": c2["exact_duplicate_rows"],
                  "rows_after_step_2": c2["rows_out"], "rows_in_year": len(readings),
                  "households_in_year": readings["LCLid"].nunique()})

    pool = complete_pool(readings, args.year, max_missing)
    sample = draw_sample(pool, args.households, args.seed)
    group = (readings.groupby("LCLid", observed=True)["tariff_group"].first()
             .rename(index=str).astype(str))
    subset, rounding = round_readings(household_days(readings, sample, args.year, signals))
    out = Path(args.out)
    csv_sha = write_subset(subset, out)
    csv_bytes = csv_inside(out)[0]
    schedule_path = out.parent / DEFAULT_SCHEDULE
    schedule_sha = write_schedule(schedule, schedule_path)

    summary = {
        "built": dt.date.today().isoformat(), "python": platform.python_version(),
        "pandas": pd.__version__, "numpy": np.__version__,
        "year": args.year, "households": args.households, "seed": args.seed,
        "pool_rule": args.pool, "downloaded": args.downloaded, "steps": steps,
        "pool": len(pool), "pool_std": int((group[pool] == "Std").sum()),
        "pool_tou": int((group[pool] == "ToU").sum()),
        "sample": len(sample), "sample_std": int((group[sample] == "Std").sum()),
        "sample_tou": int((group[sample] == "ToU").sum()),
        "first_ids": [str(i) for i in sample[:3]], "sample_sha256": sample_sha256(sample),
        "output": str(out), "output_rows": len(subset),
        "missing_readings": int(subset[READING_COLUMNS].isna().sum().sum()),
        "output_bytes": out.stat().st_size, "output_sha256": file_sha256(out),
        "output_csv_bytes": csv_bytes, "output_csv_sha256": csv_sha,
        "tariffs": tariff_summary(tariffs, gmt, signals),
        "download_readings_over_three_places": int(over.size),
        "download_first_over": first_over, "rounding": rounding,
        "schedule": {"name": schedule_path.name, "path": str(schedule_path),
                     "rows": len(schedule), "bytes": schedule_path.stat().st_size,
                     "sha256": schedule_sha},
    }
    if args.manifest:
        summary.update(lcl_csv=describe(args.lcl_csv), tariff_file=describe(args.tariffs),
                       zip=describe(args.zip) if args.zip else None)
        Path(args.manifest).write_text(manifest_text(summary), encoding="utf-8")

    for key, value in steps.items():
        print(f"{key}: {value:,}")
    for key in ("pool", "pool_std", "pool_tou", "sample", "sample_std", "sample_tou"):
        print(f"{key}: {summary[key]:,}")
    print(f"first_ids: {', '.join(summary['first_ids'])}")
    print(f"sample_sha256: {summary['sample_sha256']}")
    print(f"download readings with more than three decimals: {over.size:,}"
          + (f" (first: {first_over['LCLid']}, {first_over['stamp']}, {first_over['kwh']!r})"
             if first_over else ""))
    print(f"step 7, readings the rounding changed: {rounding['readings_changed']:,} "
          f"(largest change {rounding['largest_change']:.7f} kWh)")
    print(f"output: {out} ({summary['output_rows']:,} rows, {summary['output_bytes']:,} bytes, "
          f"{summary['output_bytes'] / 2**20:.2f} MiB)")
    print(f"output_sha256: {summary['output_sha256']}")
    print(f"output_csv: {csv_bytes:,} bytes, {csv_bytes / 2**20:.2f} MiB, sha256 {csv_sha}")
    print(f"price schedule: {schedule_path} ({len(schedule):,} half-hours, "
          f"{summary['schedule']['bytes']:,} bytes), sha256 {schedule_sha}")
    for fault in summary["tariffs"]["faults"]:
        print(f"tariff half-hour with {fault['signals']} rows: {fault['stamp']} "
              f"({fault['tariffs'] or 'none'})")
    return summary


if __name__ == "__main__":
    try:
        main()
    except ValueError as err:
        sys.exit(f"build stopped: {err}")
