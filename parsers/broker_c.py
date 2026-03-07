"""
Parser for Broker C exports.
Reads the file without headers (column titles are in row 26 area),
filters to 'Positions and Mark-to-Market Profit and Loss' / 'Summary' rows.
Handles both Excel (.xlsx/.xls) and CSV (.csv) files.
"""

import pandas as pd


def read_file_no_header(file):
    """Read a file without headers, as either Excel or CSV based on filename."""
    name = getattr(file, "name", str(file)).lower()
    if name.endswith(".csv"):
        # Broker C CSVs have inconsistent column counts across rows
        # (header sections have fewer columns than data rows).
        # Pre-define enough columns to fit the widest row.
        return pd.read_csv(
            file,
            header=None,
            names=range(30),
            on_bad_lines="skip",
        )
    else:
        return pd.read_excel(file, header=None)


def parse(file, file_config, mapping_asset_class, mapping_us_situs):
    """
    Parse a Broker C export file into the standard portfolio schema.
    """

    # --- 1. Read without headers (non-standard layout) ---
    df = read_file_no_header(file)

    # --- 2. Filter to the rows we care about ---
    df = df[
        (df[0] == "Positions and Mark-to-Market Profit and Loss")
        & (df[2] == "Summary")
    ].copy()

    # --- 3. Assign readable column names ---
    df = df.rename(
        columns={
            3: "Field Value",
            4: "Currency",
            5: "Symbol",
            6: "Description",
            12: "Market Value",
        }
    )

    # --- 4. Determine Asset Class ---
    asset_class_map = dict(
        zip(
            mapping_asset_class["Underlying Instrument Description"],
            mapping_asset_class["Asset Class"],
        )
    )

    def determine_asset_class(row):
        if row["Field Value"] == "Forex":
            return "Cash"
        if row["Field Value"] == "Stocks":
            return "Single Stock"
        desc = str(row["Description"]).strip()
        mapped = asset_class_map.get(desc, "")
        if mapped and str(mapped).strip():
            return str(mapped).strip()
        return "UNMAPPED"

    df["Asset Class"] = df.apply(determine_asset_class, axis=1)

    # --- 5. Determine US Situs Flag ---
    us_situs_map = dict(
        zip(
            mapping_us_situs["Underlying Instrument Description"],
            mapping_us_situs["US Situs Flag"],
        )
    )

    def determine_us_situs(row):
        if row["Field Value"] == "Forex":
            return "N"
        desc = str(row["Description"]).strip()
        mapped = us_situs_map.get(desc, "")
        if mapped and str(mapped).strip():
            return str(mapped).strip()
        return "UNMAPPED"

    df["US Situs Flag"] = df.apply(determine_us_situs, axis=1)

    # --- 6. Determine Currency ---
    def determine_currency(row):
        if row["Field Value"] == "Forex":
            return str(row["Symbol"]).strip()
        return str(row["Currency"]).strip()

    df["Ccy"] = df.apply(determine_currency, axis=1)

    # --- 7. Determine Asset Name ---
    def determine_asset_name(row):
        if row["Field Value"] == "Forex":
            return str(row["Symbol"]).strip() + " Cash Balance"
        return str(row["Description"]).strip()

    df["Asset Name"] = df.apply(determine_asset_name, axis=1)

    # --- 8. Build the standard output ---
    output = pd.DataFrame(
        {
            "Asset Name": df["Asset Name"].values,
            "Asset Class": df["Asset Class"].values,
            "Currency": df["Ccy"].values,
            "Institution": file_config["institution"],
            "Account Type": file_config["account_type"],
            "Jurisdiction": file_config["jurisdiction"],
            "Beneficiary": file_config["beneficiary"],
            "Balance (Local)": pd.to_numeric(df["Market Value"], errors="coerce").values,
            "Balance (USD)": None,
            "US Situs Flag": df["US Situs Flag"].values,
            "Tag": file_config.get("tag", ""),
        }
    )

    output = output.reset_index(drop=True)
    return output
