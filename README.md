# deep-learning-systems

## Project description

[TO WRITE: two to four sentences in your own words: what you built and the dataset you used.]

## Dataset

- Name: SmartMeter Energy Consumption Data in London Households, the Low Carbon London smart meter
  data (UK Power Networks)
- Source: the London Datastore,
  https://data.london.gov.uk/dataset/smartmeter-energy-use-data-in-london-households
- Licence: Creative Commons Attribution (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/,
  as the London Datastore page states
- Downloaded: 11 October 2026
- File: `lcl_2013_1000_households.csv.gz`, in this repository beside the notebook, 26,834,450
  bytes (25.59 MiB), SHA-256 `c38ee5df87c4c3f48bd0f5cbe8c299ca605f4ffb5ce1165fe3dea3406bf3b40c`.
  It is a gzip copy of the working CSV, which is 112,669,998 bytes and so over GitHub's 100 MiB
  file limit. `pandas.read_csv` reads the gzip directly, and the notebook checks its hash against
  `data_pipeline/MANIFEST.md` before it uses it.
- Price schedule: `lcl_2013_price_schedule.csv`, beside the working file, 466,443 bytes, SHA-256
  `766106ad7cafe2db3a9195f8d603ddfa2c092c3743b1625ad365dc2aac9a8e39`. It is the same data set, not
  a join: the half-hourly tariff from the download's own `Tariffs.xlsx`, written by the same
  pipeline. Task 5 reads it for one extra view.

The working file holds 1,000 households drawn with seed 42 from the 1,132 households with every
2013 reading: one row per household-day, 365,000 rows. Each row gives the household (`LCLid`),
its tariff group (`Std` or `ToU`), the date, the time-of-use group's price signal for that day,
and the day's 48 half-hourly readings in kWh, `r00` to `r47`.

The price schedule holds one row per GMT half-hour of 2013: `stamp`, and `tariff`, the price signal
the time-of-use group was given for that half-hour (`High`, `Low` or `Normal`). The tariff file
appears to follow the UK local clock (inferred from when the time-of-use households change their
use; neither file says so), so the pipeline moves its summer stamps one hour back to the readings'
GMT stamps. That move gives 2013-03-31 01:00 and 01:30 two rows each, both `Normal`, and one of each
is kept. It leaves 2013-10-27 01:00 and 01:30 with none, and they are left out. So the schedule
holds 17,518 rows, not 17,520.

### Rebuilding the working file

1. Download `LCL-FullData.zip` and `Tariffs.xlsx` from the London Datastore page above.
2. Extract `CC_LCL-FullData.csv` from the zip. The zip is compressed with Deflate64, which
   Python's `zipfile` cannot open, so use a tool that handles it, such as Info-ZIP `unzip` or
   7-Zip.
3. Run the pipeline, which needs only the standard library and pandas:

   ```bash
   python data_pipeline/build_lcl_subset.py --lcl-csv CC_LCL-FullData.csv --tariffs Tariffs.xlsx
   ```

With its defaults it rebuilds `lcl_2013_1000_households.csv.gz` byte for byte, and writes
`lcl_2013_price_schedule.csv` beside it, also byte for byte.
`data_pipeline/MANIFEST.md` gives the sizes and SHA-256 hashes of the download, the extracted CSV
and the output, and the count after each step.

To adapt it, `--year`, `--households`, `--seed` and `--pool` (`strict`, or `at-most-N` for
households with at most N readings missing) change what it draws, and `--out` where it writes.
Two caveats: an `at-most-N` pool leaves empty readings that the notebook does not fill, and the
price signals exist for 2013 only, so in any other year `price_signal` is empty.

## Report

The report ships twice with the same content, as `Deep_Learning_Systems_Analysis_Report.pdf` and
as `module_summary.pdf`, because the brief names it both ways.

## How to run

These steps assume Python 3 and Git are installed. The notebook was built with Python 3.12.

1. Clone this repository and move into its folder.
2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows, activate it with `.venv\Scripts\activate` instead.

3. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Open the notebook, then restart the kernel and run all cells:

   ```bash
   jupyter notebook deep_learning.ipynb
   ```

The notebook trains both models every time it runs. On an NVIDIA GeForce RTX 5090 the last full
run spent 21.4 minutes training. With no GPU visible the same code runs on the CPU, and
Task 5's timing table estimates that at about 49.5 hours, scaled from the median of 20 timed
training steps of each model on this rig's CPU, with PyTorch fixed at 16 threads. Its first
code cell pins the first GPU and sets the seeds and the settings that make a rerun repeat its
numbers. Running the notebook writes the trained weights, the epoch logs, the forecasts and the
figures to `outputs/`, which is not part of the repository.

The environment check cell is the brief's own validation code, kept exactly as given. Because it
imports its libraries after the first code cell has set the GPU, flake8 reports its imports as
E402 (module level import not at top of file); that is the one known exception.

## How requirements.txt was created

The notebook was run top to bottom in a fresh virtual environment, and the file was then written
from that environment with:

```bash
pip freeze > requirements.txt
```

A second fresh environment installed from that file alone ran the notebook again.
