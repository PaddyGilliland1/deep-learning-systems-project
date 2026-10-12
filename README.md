# deep-learning-systems

## Project description

**What I built:** I forecast a London household's electricity use for the next 24 hours, which is 48
half-hourly meter readings, from its previous seven days.

**The models:** I compared a long short-term memory (LSTM) network with the same network built from
gated recurrent unit (GRU) layers.

**The data:** I used Low Carbon London smart meter data from UK Power Networks, for 1,000 households
with a complete 2013 record.

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
  file limit. `pandas.read_csv` reads the gzip directly. The brief's environment check loads it
  first, as given, and the first cell of Task 2 then checks its hash against
  `data_pipeline/MANIFEST.md` and stops the notebook if it differs.
- Price schedule: `lcl_2013_price_schedule.csv`, beside the working file, 466,443 bytes, SHA-256
  `766106ad7cafe2db3a9195f8d603ddfa2c092c3743b1625ad365dc2aac9a8e39`. It is the same data set, not
  a join: the half-hourly tariff from `Tariffs.xlsx`, a separate file on the same London Datastore
  page as the readings and part of the same data set, not inside the readings zip. The same
  pipeline writes it, and Task 5 reads it for one extra view.

The working file holds 1,000 households drawn with seed 42 from the 1,132 households with every
2013 reading: one row per household-day, 365,000 rows. Each row gives the household (`LCLid`),
its tariff group (`Std` or `ToU`), the date, the time-of-use group's price signal for that day,
and the day's 48 half-hourly readings in kWh, `r00` to `r47`.

The price schedule holds one row per Greenwich Mean Time (GMT) half-hour of 2013: `stamp`, and
`tariff`, the price signal the time-of-use group was given for that half-hour (`High`, `Low` or
`Normal`). The tariff file appears to follow the UK local clock, so the pipeline moves its summer
stamps one hour back to the readings' GMT stamps. That is my inference from when the time-of-use
households change their use, as neither file says so. That move gives 2013-03-31 01:00 and 01:30 two rows each, both `Normal`, and one of each
is kept. It leaves 2013-10-27 01:00 and 01:30 with none, and they are left out. So the schedule
holds 17,518 rows, not 17,520.

### Rebuilding the working file

1. Download `LCL-FullData.zip` and `Tariffs.xlsx` from the London Datastore page above.
2. Extract `CC_LCL-FullData.csv` from the zip. The zip is compressed with Deflate64, which
   Python's `zipfile` cannot open, so use a tool that handles it, such as Info-ZIP `unzip` or
   7-Zip.
3. Run the pipeline, which needs only the standard library, NumPy and pandas:

   ```bash
   python data_pipeline/build_lcl_subset.py --lcl-csv CC_LCL-FullData.csv --tariffs Tariffs.xlsx
   ```

With its defaults it rebuilds the CSV inside `lcl_2013_1000_households.csv.gz` byte for byte,
and the gzip itself too with a standard zlib. It writes `lcl_2013_price_schedule.csv` beside it,
also byte for byte. `data_pipeline/MANIFEST.md` gives the sizes and SHA-256 hashes of the
download, the extracted CSV and the output, and the count after each step. On this rig the last
rebuild took about 3 minutes, and its peak memory was 15.5 GiB (measured with
`/usr/bin/time -v`), so it needs a machine with more than 16 GB of memory.

To adapt it, `--year`, `--households`, `--seed` and `--pool` (`strict`, or `at-most-N` for
households with at most N readings missing) change what it draws, and `--out` where it writes.
There are three caveats. `--out` defaults to the shipped file, and the price schedule is always
written beside it, so give an adapted build its own `--out`. The notebook is written for the
default build: it stops on the empty readings an `at-most-N` pool leaves, and on any year but
2013. The price signals exist for 2013 only, so in any other year `price_signal` is empty.

## Report

The report ships twice with the same content, as `Deep_Learning_Systems_Analysis_Report.pdf` and
as `module_summary.pdf`, because the brief names it both ways.

## How to run

These steps need Git and Python 3.12, the version the notebook was built and tested with
(3.12.3). Several pins, NumPy 2.5.4 among them, need Python 3.12 or later. `requirements.txt`
stays the `pip freeze` of the environment the notebook ran in, on 64-bit Linux under Windows
Subsystem for Linux (WSL2), so the steps below are for 64-bit Linux, or WSL2 on Windows.

1. Clone this repository and move into its folder.
2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Open the notebook, then restart the kernel and run all cells:

   ```bash
   jupyter notebook deep_learning.ipynb
   ```

**On Windows outside WSL2, or macOS on Apple silicon.** The `nvidia-` and `cuda-` lines and
`triton` in `requirements.txt` are PyTorch's Linux CUDA packages, which have no Windows or macOS
build, so step 3 stops there. On Windows, activate the environment with `.venv\Scripts\activate`.
Then install PyTorch 2.14.1 for your system with the command https://pytorch.org gives. On
Windows, its CUDA build uses an NVIDIA card, and the plain `pip install torch==2.14.1` runs on the
central processing unit (CPU). Then install the other pins without the Linux-only lines. On
macOS:

```bash
grep -v -E "^(nvidia-|cuda-|triton)" requirements.txt > requirements-other.txt
pip install -r requirements-other.txt
```

On Windows, in PowerShell:

```powershell
Get-Content requirements.txt | Where-Object { $_ -notmatch '^(nvidia-|cuda-|triton)' } | Set-Content requirements-other.txt
pip install -r requirements-other.txt
```

Every remaining pin has a Python 3.12 wheel for 64-bit Windows and for macOS 14 or later on Apple
silicon, and the pins resolve together on both (checked with `uv pip compile` for each platform).
PyTorch 2.14.1 publishes no build for macOS on Intel, so this route does not work there.

The notebook trains both models every time it runs. On an NVIDIA GeForce RTX 5090 the last full
run spent 21.2 minutes training. With no graphics processing unit (GPU) visible the same code
runs on the CPU, and Task 5's timing table estimates that at about 50.7 hours, scaled from the median of 20 timed
training steps of each model on this rig's CPU, with PyTorch fixed at 16 threads. This rig's CPU
is an Intel Core Ultra 9 285K. The notebook's first code cell pins the first GPU and sets the
seeds and the settings that make a rerun repeat its numbers. Running the notebook writes the
trained weights, the epoch logs, the forecasts and the figures to `outputs/`, which is not part
of the repository.

On a GPU, a training watchdog ends a run early if one epoch takes more than three times the median
of the epochs before it, or if the run passes two hours. That can happen on a shared GPU or on a
machine that sleeps. The run then keeps its best epoch so far, the notebook prints a warning and
carries on, and that run's figures can differ from those shown. A loss that is not a number
stops the notebook on any device.

The environment check cell is the brief's own validation code, kept exactly as given. Because it
imports its libraries after the first code cell has set the GPU, flake8 reports its imports as
E402 (module level import not at top of file). That is the one known exception.

## How requirements.txt was created

The notebook was run top to bottom in a fresh virtual environment, and the file was then written
from that environment with:

```bash
pip freeze > requirements.txt
```

A second fresh environment installed from that file alone ran the notebook again.
