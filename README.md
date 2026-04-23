# Portfolio Analyser

A Streamlit dashboard that aggregates investment data from multiple brokers and manual entries into a unified portfolio view.

## Setup

1. Open a terminal in this folder
2. Create a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # Mac/Linux
   ```
3. Install dependencies:
   ```
   pip install streamlit pandas plotly openpyxl pyyaml requests
   pip freeze > requirements.txt
   ```

## Running

```
streamlit run app.py
```

A browser tab will open at http://localhost:8501 showing your dashboard.

## Project Structure

```
portfolio-analyser/
├── app.py                              # Main Streamlit dashboard
├── fx_rates.py                         # FX rate fetcher (USD base)
├── parsers/
│   ├── broker_a.py                     # Saxo export parser
│   └── (broker_b.py)                   # To be added
├── config/
│   ├── sources.yaml                    # File-level attributes per broker
│   ├── asset_class_labels.csv          # A=Cash, B=S&P Equivalent, etc.
│   ├── mapping_asset_class.csv         # Maps instrument names → asset class
│   └── mapping_us_situs.csv            # Maps instrument names → US situs flag
└── .gitignore
```

## Configuration

### sources.yaml
Defines file-level attributes (institution, jurisdiction, beneficiary) for each broker source. When you upload a file, these are applied to every line item.

### Mapping Tables
- **mapping_asset_class.csv** — Maps each instrument name to an asset class code (A-K). Only needed for instruments that aren't Cash or Stock (which are auto-detected).
- **mapping_us_situs.csv** — Maps each instrument name to Y/N for US estate tax situs. Cash is automatically N.

Add your actual instrument names to these files as you go. Any unmapped instruments will show as "UNMAPPED" in the dashboard with a warning.

## Adding a New Broker

1. Create a new parser file in `parsers/` (copy broker_a.py as a template)
2. Add the broker's config to `sources.yaml`
3. Add the upload section in `app.py`
