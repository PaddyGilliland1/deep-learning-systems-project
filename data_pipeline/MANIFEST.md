# Manifest: the Low Carbon London working subset

Written by `data_pipeline/build_lcl_subset.py` on 2026-10-11, with Python 3.12.3, pandas 3.0.6 and NumPy 2.5.4. Year 2013, 1,000 households, seed 42, pool `strict`.

## Source

| Item | Value |
|---|---|
| Data set | SmartMeter Energy Consumption Data in London Households |
| Publisher | UK Power Networks (Low Carbon London project), on the London Datastore |
| Page | https://data.london.gov.uk/dataset/smartmeter-energy-use-data-in-london-households |
| Licence | Creative Commons Attribution (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/ |
| Readings file | https://data.london.gov.uk/download/vqm0d/3527bf39-d93e-4071-8451-df2ade1ea4f2/LCL-FullData.zip |
| Tariff file | https://data.london.gov.uk/download/vqm0d/14855047-44c2-4856-8a48-e5649200e6ce/Tariffs.xlsx |
| Downloaded | 11 October 2026 |

## Files

| File | Bytes | MiB | SHA-256 |
|---|---|---|---|
| `LCL-FullData.zip` (the download) | 801,674,949 | 764.54 | `68a35598cc8e70898a7651c482216fb096a0a6910c2d180c616632dfc7a9b014` |
| `CC_LCL-FullData.csv` (extracted from the download) | 8,542,818,238 | 8,147.07 | `1df23797368237f41831434b9add6540df8a68001dabf36242d52ca41807511f` |
| `Tariffs.xlsx` (the download) | 245,384 | 0.23 | `8a2eff6dcb737aee96cfa6c357d2947604d7f812896405c2ab5f98433d2cb150` |
| `lcl_2013_1000_households.csv.gz` (the output) | 26,957,559 | 25.71 | `9fd762e499e60c7bc17db319282707b34864f8b9a3478dd872d9c2037a399c49` |
| `lcl_2013_1000_households.csv` (the CSV inside the gzip) | 113,142,976 | 107.90 | `633bb9451772773a55c8c5a653a922fe73f4288e3870b1cd0b06f0d86823cc8a` |

## The publisher's figures beside the measured ones

| Figure | On the London Datastore page | Measured |
|---|---|---|
| Download size | 764.54 MB | 801,674,949 bytes, which is 764.54 MiB |
| Unzipped size | "around 10GB when unzipped" | 8,542,818,238 bytes, which is 7.96 GiB or 8.54 GB |
| Rows | "around 167million rows" | 167,932,474 rows |
| Households | "a sample of 5,567 London Households" | 5,566 household IDs |
| Tariff file size | 239.63 kB | 245,384 bytes, which is 239.63 KiB |

## Pipeline steps

| Step | Count |
|---|---|
| Rows read | 167,932,474 |
| Households read | 5,566 |
| Step 1, "Null" readings | 5,560 |
| Step 1, rows off the half-hour grid | 5,560 |
| Step 1, rows both "Null" and off the grid | 5,560 |
| Step 1, rows dropped | 5,560 |
| Step 1, rows left | 167,926,914 |
| Step 2, exact duplicates dropped | 115,453 |
| Step 2, rows left | 167,811,461 |
| Step 3, rows in 2013 | 93,024,217 |
| Step 3, households with a reading in 2013 | 5,528 |
| Step 4, households in the pool | 1,132 |
| Step 4, pool, standard tariff group | 881 |
| Step 4, pool, time-of-use group | 251 |
| Step 5, households drawn | 1,000 |
| Step 5, sample, standard tariff group | 781 |
| Step 5, sample, time-of-use group | 219 |
| Step 5, first three IDs | MAC000006, MAC000010, MAC000018 |
| Step 6, SHA-256 of the sorted IDs | `b8700c6c0b681e278833fe87b4fdfad0ffe3ecc3fd5799b8a55803fc37dec06c` |
| Output rows | 365,000 |
| Output readings left empty | 0 |

## Price signals

The tariff file appears to follow the UK local clock (inferred from when the time-of-use households change their use; neither file says so). Its stamps inside British Summer Time move one hour back to the readings' GMT stamps.

| Item | Count |
|---|---|
| Tariff rows | 17,520 |
| High half-hours | 788 |
| Low half-hours | 1,660 |
| Days with a High signal, by the file's own dates | 77 |
| Days with a Low signal, by the file's own dates | 104 |
| Days with a High signal, GMT | 77 |
| Days with a Low signal, GMT | 104 |
| Days with both, GMT | 28 |
| Days with either, GMT | 153 |

GMT half-hours that get two tariff rows or none after the move:

| GMT half-hour | Tariff rows | Values |
|---|---|---|
| 2013-03-31 01:00:00 | 2 | Normal, Normal |
| 2013-03-31 01:30:00 | 2 | Normal, Normal |
| 2013-10-27 01:00:00 | 0 | none |
| 2013-10-27 01:30:00 | 0 | none |
