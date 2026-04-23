# Portfolio Allocation Tool

A Streamlit dashboard that aggregates investment data from multiple broker exports and manual entries into a unified portfolio view, with FX conversion to USD and allocation breakdowns across asset class, currency, jurisdiction, beneficiary, and US situs.

## Features

- Upload broker exports (Excel or CSV) and merge them with manual entries into a single master view
- Automatic FX conversion to USD using live rates (cached for offline use)
- Allocation charts by asset class, broad asset class, currency, institution, jurisdiction, beneficiary, and US situs flag
- Currency look-through for fund/ETF exposures (e.g., a GBP-denominated global equity fund broken down into its underlying currency mix)
- Session persistence — the last compiled view is saved locally and reloaded on restart
- Pluggable parser architecture — each broker has its own parser module

## Setup

1. Open a terminal in this folder.

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate     # Mac/Linux
   venv\Scripts\activate        # Windows
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create the config files the app needs (see **Configuration** below). These are not committed to the repo.

## Running

```bash
streamlit run app.py
```

A browser tab will open at http://localhost:8501.

To stop the app, press `Ctrl+C` in the terminal.

## Project Structure

```
portfolio-allocation/
├── app.py                      # Main Streamlit dashboard
├── fx_rates.py                 # FX rate fetcher and USD conversion
├── requirements.txt            # Pinned dependencies
├── parsers/
│   ├── __init__.py
│   ├── broker_a.py             # Parser for Broker A exports
│   ├── broker_c.py             # Parser for Broker C exports
│   └── manual.py               # Parser for manual entries
├── .streamlit/
│   └── config.toml             # Streamlit theme and settings
├── config/                     # Local only — not tracked by git
└── data/                       # Local only — not tracked by git
```

## Configuration

The `config/` folder holds the mapping tables and broker metadata the app needs at runtime. It is intentionally gitignored (it contains institution-specific detail), so a fresh clone will not run until you populate it.

The files expected are:

- `sources.yaml` — file-level attributes (institution, account type, jurisdiction, beneficiary) for each broker source
- `asset_class_labels.csv` — human-readable labels for asset class codes (e.g. A = Cash, B = S&P Equivalent)
- `mapping_asset_class.csv` — maps each instrument name to an asset class code. Cash and single stocks are auto-detected, so this is only needed for other instruments
- `mapping_broad_asset_class.csv` — maps each asset class to a broad asset class grouping
- `mapping_us_situs.csv` — maps each instrument name to Y/N for US estate tax situs. Cash is automatically N
- `currency_lookthrough.csv` — optional; maps multi-currency assets (funds, ETFs) to their underlying currency weights
- `fx_rates_cache.json` — auto-generated FX rate cache (safe to delete; will be re-fetched on next run)

Any instrument not found in `mapping_asset_class.csv` or `mapping_us_situs.csv` will display as "UNMAPPED" in the dashboard with a warning — add it to the relevant mapping file as you go.

## Adding a New Broker

1. Create a new parser file in `parsers/` — copy `broker_a.py` as a starting template
2. Implement the `parse(file, file_config, mapping_asset_class, mapping_us_situs)` function returning a DataFrame in the standard schema (see below)
3. Register the parser in `PARSERS` inside `app.py`
4. Add a new broker entry to `config/sources.yaml`
5. Add an upload section for the new broker in `app.py`

### Standard output schema

Each parser returns a DataFrame with these columns:

| Column | Notes |
|---|---|
| Asset Name | Instrument name or cash descriptor (e.g. "EUR Cash Balance") |
| Asset Class | Asset class code, or "Cash" / "Single Stock" for auto-detected rows |
| Currency | ISO currency code (e.g. USD, EUR, GBP) |
| Institution | From `file_config` |
| Account Type | From `file_config` |
| Jurisdiction | From `file_config` |
| Beneficiary | From `file_config` |
| Balance (Local) | Amount in the instrument's native currency |
| Balance (USD) | USD equivalent; usually left `None` and populated downstream by `fx_rates.convert_to_usd`. Parsers may pre-fill this if the broker already provides a reliable USD amount (see **Known Quirks**) |
| US Situs Flag | "Y", "N", or "UNMAPPED" |
| Tag | Optional free-text tag from `file_config` |

## Known Quirks

### Broker C cash rows

Broker C reports cash (Forex) balances with the `Market Value` column already in USD, not in the cash's native currency. To handle this correctly, `parsers/broker_c.py` takes the native amount from column I (the native-currency quantity) for `Balance (Local)` and uses the USD value directly from column M for `Balance (USD)` — rather than applying an FX conversion on top, which would double-count.

To avoid `fx_rates.convert_to_usd` overwriting these pre-populated USD values, it now preserves any existing `Balance (USD)` entry and only fills in rows where it is missing. Any future broker parser that has a reliable direct USD amount can take advantage of the same pattern.

### FX rates

FX rates are fetched live from `exchangerate-api.com` (no key required) and cached to `config/fx_rates_cache.json`. If the API is unreachable, the cached file is used; if neither is available, all non-USD balances will fail to convert. The cache can be deleted at any time to force a fresh fetch.

### Column layout changes

Broker export formats change from time to time. If a parser suddenly produces wrong or empty values after a broker update, the most likely cause is that a column has shifted — open a recent export and verify the column indices used inside the parser's `rename` call still point to the right fields.

## Tech Stack

- **Python** with Streamlit for the dashboard
- **pandas** for data wrangling
- **Plotly** for charts
- **PyYAML** for config
- **requests** for the FX rate API
- **openpyxl** / **xlrd** for Excel file reading
