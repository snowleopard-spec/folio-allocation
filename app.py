"""
Portfolio Allocation Tool - Main Dashboard
============================================
Run with: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import yaml
import traceback
import os
import json
import io
from datetime import date
import plotly.graph_objects as go

from parsers.broker_a import parse as parse_broker_a
from parsers.broker_c import parse as parse_broker_c
from parsers.manual import parse as parse_manual
from fx_rates import fetch_fx_rates, convert_to_usd

# --- Page config ---
st.set_page_config(page_title="Portfolio Allocation Tool", layout="wide")

# --- Custom styling ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600&display=swap');

    h1, h2, h3 {
        font-family: 'Avenir Next', 'Avenir', -apple-system, BlinkMacSystemFont, sans-serif !important;
        color: #3D3229 !important;
        font-weight: 600 !important;
    }
    h1 { letter-spacing: -0.5px; }

    .stMarkdown, .stText, p, span, label {
        font-family: 'Source Sans Pro', sans-serif !important;
    }

    .stButton > button[kind="primary"] {
        background-color: #8B7355 !important;
        border: none !important;
        color: white !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #74604A !important;
    }
    .stButton > button[kind="secondary"] {
        border-color: #8B7355 !important;
        color: #8B7355 !important;
    }

    [data-testid="stMetricValue"] {
        font-family: 'Avenir Next', 'Avenir', -apple-system, BlinkMacSystemFont, sans-serif !important;
        color: #3D3229 !important;
    }

    .stDataFrame { border-radius: 4px; }
    .block-container { padding-top: 2rem !important; }
    [data-testid="stFileUploader"] { border-color: #C4B8A8 !important; }
    .stAlert { border-radius: 4px !important; }

    /* Remove gridlines from legend tables */
    .stMarkdown table td,
    .stMarkdown table th {
        border: none !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="color:#556B2F !important;">Portfolio Allocation Tool</h1>', unsafe_allow_html=True)

# --- Constants ---
SAVE_DIR = "data"
SAVE_PATH = os.path.join(SAVE_DIR, "last_compiled.parquet")
META_PATH = os.path.join(SAVE_DIR, "last_compiled_meta.json")

# --- Initialise session state ---
for key, default in [
    ("compiled_master", None), ("compile_log", []), ("compile_errors", []),
    ("price_errors", []), ("yfinance_error", False), ("fetched_prices", {}),
    ("upload_key", 0), ("display_rates", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# --- Load configuration ---
with open("config/sources.yaml") as f:
    sources_config = yaml.safe_load(f)

mapping_asset_class = pd.read_csv("config/mapping_asset_class.csv")
mapping_us_situs = pd.read_csv("config/mapping_us_situs.csv")
mapping_broad_ac = pd.read_csv("config/mapping_broad_asset_class.csv")
asset_class_labels = pd.read_csv("config/asset_class_labels.csv")

lookthrough_path = "config/currency_lookthrough.csv"
if os.path.exists(lookthrough_path):
    currency_lookthrough = pd.read_csv(lookthrough_path)
else:
    currency_lookthrough = pd.DataFrame(columns=["Asset Name", "Currency", "Weight"])

broad_ac_map = dict(zip(mapping_broad_ac["Asset Class"], mapping_broad_ac["Broad Asset Class"]))

PARSERS = {
    "broker_a": parse_broker_a,
    "broker_c": parse_broker_c,
    "manual": parse_manual,
}

rates = fetch_fx_rates()
fx_error = rates is None or len(rates) <= 1

PLOTLY_COLORS = [
    "#8B7355", "#B8860B", "#6B8E6B", "#A0522D", "#708090",
    "#CD853F", "#556B2F", "#8B6914", "#7B6B5A", "#9E7B5B",
]


def fmt_k(value):
    return f"${value/1000:,.0f}k"


def apply_currency_lookthrough(data, lookthrough_df):
    if lookthrough_df.empty:
        return data
    lookthrough_assets = lookthrough_df["Asset Name"].unique()
    mask = data["Asset Name"].isin(lookthrough_assets)
    passthrough = data[~mask].copy()
    to_explode = data[mask].copy()
    if to_explode.empty:
        return data
    exploded_rows = []
    for _, row in to_explode.iterrows():
        asset_lt = lookthrough_df[lookthrough_df["Asset Name"] == row["Asset Name"]]
        for _, lt_row in asset_lt.iterrows():
            new_row = row.copy()
            new_row["Currency"] = lt_row["Currency"]
            new_row["Balance (USD)"] = row["Balance (USD)"] * lt_row["Weight"]
            new_row["Balance (Local)"] = row["Balance (Local)"] * lt_row["Weight"]
            exploded_rows.append(new_row)
    if exploded_rows:
        return pd.concat([passthrough, pd.DataFrame(exploded_rows)], ignore_index=True)
    return passthrough


def get_chart_data(data, attribute, value_col="Balance (USD)"):
    grouped = data.groupby(attribute)[value_col].sum().reset_index()
    grouped = grouped.sort_values(value_col, ascending=False).reset_index(drop=True)
    total = grouped[value_col].sum()
    if total == 0:
        return [], 0
    return [(str(row[attribute]), row[value_col], (row[value_col] / total) * 100) for _, row in grouped.iterrows()], total


def make_allocation_bar(data, attribute, value_col="Balance (USD)"):
    chart_rows, total = get_chart_data(data, attribute, value_col)
    if total == 0:
        return None, None, None

    fig = go.Figure()
    legend_parts, hidden_parts = [], []

    for i, (label, value, pct) in enumerate(chart_rows):
        color = PLOTLY_COLORS[i % len(PLOTLY_COLORS)]
        text = f"{label}: {pct:.1f}%" if pct >= 12 else ""
        fig.add_trace(go.Bar(
            y=[""], x=[value], name=label, orientation="h",
            text=text, textposition="inside",
            textfont=dict(size=12, color="white"), marker_color=color,
            hovertemplate=f"{label}<br>{fmt_k(value)}<br>{pct:.1f}%<extra></extra>",
        ))
        swatch = (f'<td style="padding:3px 8px 3px 0;"><span style="display:inline-block;width:14px;height:14px;'
                  f'background-color:{color};border-radius:2px;vertical-align:middle;"></span></td>')
        legend_parts.append(
            f'<tr>{swatch}<td style="padding:3px 12px 3px 0;color:#3D3229;">{label}</td>'
            f'<td style="padding:3px 12px 3px 0;text-align:right;color:#3D3229;">{fmt_k(value)}</td>'
            f'<td style="padding:3px 0;text-align:right;color:#3D3229;">{pct:.1f}%</td></tr>')
        hidden_parts.append(
            f'<tr>{swatch}<td style="padding:3px 12px 3px 0;color:#3D3229;">{label}</td>'
            f'<td style="padding:3px 0;text-align:right;color:#3D3229;">{pct:.1f}%</td></tr>')

    fig.update_layout(
        barmode="stack", showlegend=False, height=70,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )

    tbl = 'style="font-size:14px;margin-top:4px;font-family:Source Sans Pro,sans-serif;border-collapse:collapse;"'
    hdr = 'style="font-weight:600;border-bottom:1px solid #C4B8A8;color:#8B7355;"'
    bold = 'style="padding:4px 12px 3px 0;color:#8B7355;font-weight:600;"'
    bold_r = 'style="padding:4px 0;text-align:right;color:#8B7355;font-weight:600;"'
    bold_r2 = 'style="padding:4px 12px 3px 0;text-align:right;color:#8B7355;font-weight:600;"'

    legend_html = (
        f'<table {tbl}>'
        f'<tr {hdr}><td style="padding:3px 8px 3px 0;"></td>'
        f'<td style="padding:3px 12px 3px 0;">Category</td>'
        f'<td style="padding:3px 12px 3px 0;text-align:right;">Balance (USD)</td>'
        f'<td style="padding:3px 0;text-align:right;">Weight</td></tr>'
        + "".join(legend_parts)
        + f'<tr style="border-top:1px solid #C4B8A8;"><td style="padding:4px 8px 3px 0;"></td>'
        f'<td {bold}>Total</td><td {bold_r2}>{fmt_k(total)}</td><td {bold_r}>100.0%</td></tr></table>')

    hidden_html = (
        f'<table {tbl}>'
        f'<tr {hdr}><td style="padding:3px 8px 3px 0;"></td>'
        f'<td style="padding:3px 12px 3px 0;">Category</td>'
        f'<td style="padding:3px 0;text-align:right;">Weight</td></tr>'
        + "".join(hidden_parts)
        + f'<tr style="border-top:1px solid #C4B8A8;"><td style="padding:4px 8px 3px 0;"></td>'
        f'<td {bold}>Total</td><td {bold_r}>100.0%</td></tr></table>')

    return fig, legend_html, hidden_html


def make_grey_table(headers, rows):
    header_html = "".join(
        f'<th style="padding:4px 10px;text-align:left;border-bottom:1px solid #C4B8A8;">{h}</th>'
        for h in headers)
    rows_html = "".join(
        "<tr>" + "".join(f'<td style="padding:3px 10px;">{cell}</td>' for cell in row) + "</tr>"
        for row in rows)
    return (f'<table style="font-size:13px;color:#A09080;width:100%;font-family:Source Sans Pro,sans-serif;'
            f'border-collapse:collapse;"><tr style="color:#8B7355;font-weight:600;">{header_html}</tr>{rows_html}</table>')


# --- PDF generation ---
def generate_pdf(master_df, chart_configs, ref_rates, stock_prices, hide_balances=False):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.colors import HexColor

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    margin = 25 * mm
    usable_w = w - 2 * margin
    olive = HexColor("#556B2F")
    brown = HexColor("#8B7355")
    dark = HexColor("#3D3229")
    muted = HexColor("#A09080")
    border_color = HexColor("#C4B8A8")

    y = h - margin

    # Title
    c.setFont("Times-Bold", 22)
    c.setFillColor(olive)
    c.drawString(margin, y, f"Asset Allocation as of {date.today().strftime('%d %B %Y')}")
    y -= 14 * mm

    # Charts
    for label, chart_data, attribute in chart_configs:
        chart_rows, total = get_chart_data(chart_data, attribute)
        if total == 0:
            continue

        block_height = 20 * mm + (len(chart_rows) + 2) * 5 * mm
        if y - block_height < margin + 40 * mm:
            c.showPage()
            y = h - margin

        # Section label
        c.setFont("Times-Bold", 13)
        c.setFillColor(dark)
        c.drawString(margin, y, label)
        y -= 7 * mm

        # Stacked bar
        bar_h = 10 * mm
        x_pos = margin
        for i, (cat_label, value, pct) in enumerate(chart_rows):
            color = PLOTLY_COLORS[i % len(PLOTLY_COLORS)]
            seg_w = (pct / 100) * usable_w
            c.setFillColor(HexColor(color))
            c.rect(x_pos, y - bar_h, seg_w, bar_h, fill=1, stroke=0)
            if pct >= 12:
                c.setFillColor(HexColor("#FFFFFF"))
                c.setFont("Helvetica", 7)
                txt = f"{cat_label}: {pct:.1f}%"
                if c.stringWidth(txt, "Helvetica", 7) < seg_w - 4:
                    c.drawString(x_pos + 3, y - bar_h + 3, txt)
            x_pos += seg_w
        y -= bar_h + 6 * mm

        # Table
        col_cat = margin + 8 * mm
        col_bal = margin + usable_w * 0.7
        col_wt = margin + usable_w - 2 * mm

        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(brown)
        c.drawString(col_cat, y, "Category")
        if not hide_balances:
            c.drawRightString(col_bal, y, "Balance (USD)")
        c.drawRightString(col_wt, y, "Weight")
        y -= 1.5 * mm
        c.setStrokeColor(border_color)
        c.setLineWidth(0.5)
        c.line(margin, y, margin + usable_w, y)
        y -= 4 * mm

        c.setFont("Helvetica", 8)
        for i, (cat_label, value, pct) in enumerate(chart_rows):
            color = PLOTLY_COLORS[i % len(PLOTLY_COLORS)]
            c.setFillColor(HexColor(color))
            c.rect(margin, y - 1, 4 * mm, 4 * mm, fill=1, stroke=0)
            c.setFillColor(dark)
            c.drawString(col_cat, y, cat_label)
            if not hide_balances:
                c.drawRightString(col_bal, y, fmt_k(value))
            c.drawRightString(col_wt, y, f"{pct:.1f}%")
            y -= 4.5 * mm

        # Total — extra spacing before the line
        y -= 1.5 * mm
        c.setStrokeColor(border_color)
        c.line(margin, y + 3.5 * mm, margin + usable_w, y + 3.5 * mm)
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(brown)
        c.drawString(col_cat, y, "Total")
        if not hide_balances:
            c.drawRightString(col_bal, y, fmt_k(total))
        c.drawRightString(col_wt, y, "100.0%")
        y -= 9 * mm

    # Reference Data
    if y < margin + 50 * mm:
        c.showPage()
        y = h - margin

    y -= 2 * mm
    c.setStrokeColor(border_color)
    c.line(margin, y, margin + usable_w, y)
    y -= 7 * mm

    c.setFont("Times-Bold", 12)
    c.setFillColor(muted)
    c.drawString(margin, y, "Reference Data")
    y -= 8 * mm

    if ref_rates and len(ref_rates) > 1:
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(muted)
        c.drawString(margin, y, "FX Rates")
        y -= 5 * mm
        # Header line
        c.setStrokeColor(border_color)
        c.setLineWidth(0.5)
        ref_col1 = margin + 4 * mm
        ref_col2 = margin + 35 * mm
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(brown)
        c.drawString(ref_col1, y, "Pair")
        c.drawString(ref_col2, y, "Rate")
        y -= 1.5 * mm
        c.line(margin, y, margin + 60 * mm, y)
        y -= 4 * mm
        c.setFont("Helvetica", 8)
        for ccy in ["GBP", "EUR", "SGD", "AUD", "HKD", "JPY"]:
            if ccy in ref_rates:
                c.setFillColor(muted)
                c.drawString(ref_col1, y, f"{ccy}/USD")
                c.drawString(ref_col2, y, f"{1/ref_rates[ccy]:.4f}")
                y -= 4 * mm
        y -= 3 * mm

    if stock_prices:
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(muted)
        c.drawString(margin, y, "Stock Prices")
        y -= 5 * mm
        # Header line
        c.setStrokeColor(border_color)
        c.setLineWidth(0.5)
        ref_col1 = margin + 4 * mm
        ref_col2 = margin + 35 * mm
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(brown)
        c.drawString(ref_col1, y, "Ticker")
        c.drawString(ref_col2, y, "Price")
        y -= 1.5 * mm
        c.line(margin, y, margin + 60 * mm, y)
        y -= 4 * mm
        c.setFont("Helvetica", 8)
        for ticker, price in sorted(stock_prices.items()):
            c.setFillColor(muted)
            c.drawString(ref_col1, y, ticker)
            c.drawString(ref_col2, y, f"{price:,.4f}")
            y -= 4 * mm

    c.save()
    buf.seek(0)
    return buf.getvalue()


# --- Save/Load helpers ---
def save_compiled(df, fx_rates, stock_prices):
    os.makedirs(SAVE_DIR, exist_ok=True)
    df.to_parquet(SAVE_PATH, index=False)
    meta = {"fx_rates": fx_rates if fx_rates else {}, "stock_prices": stock_prices if stock_prices else {}}
    with open(META_PATH, "w") as f:
        json.dump(meta, f)


def load_compiled():
    if not os.path.exists(SAVE_PATH):
        return None, None, None
    df = pd.read_parquet(SAVE_PATH)
    saved_rates, saved_prices = None, None
    if os.path.exists(META_PATH):
        with open(META_PATH) as f:
            meta = json.load(f)
        saved_rates = meta.get("fx_rates", {})
        saved_prices = meta.get("stock_prices", {})
    return df, saved_rates, saved_prices


def has_saved_data():
    return os.path.exists(SAVE_PATH)


def get_saved_timestamp():
    if os.path.exists(SAVE_PATH):
        mtime = os.path.getmtime(SAVE_PATH)
        from datetime import datetime
        return datetime.fromtimestamp(mtime).strftime("%d %b %Y, %H:%M")
    return None


# ============================================================
# SECTION: Upload & Assign Sources
# ============================================================
st.header("Upload Files")

if has_saved_data() and st.session_state.compiled_master is None:
    ts = get_saved_timestamp()
    col_load, col_spacer = st.columns([1, 2])
    with col_load:
        if st.button(f"Load previous ({ts})", type="secondary"):
            loaded, saved_rates, saved_prices = load_compiled()
            if loaded is not None:
                st.session_state.compiled_master = loaded
                st.session_state.compile_log = [f"Loaded from saved file ({len(loaded)} items, saved {ts})"]
                if saved_rates:
                    st.session_state.display_rates = saved_rates
                if saved_prices:
                    st.session_state.fetched_prices = saved_prices
                st.rerun()

uploaded_files = st.file_uploader(
    "Upload all broker and manual files",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    key=f"uploader_{st.session_state.upload_key}",
)

source_names = list(sources_config["sources"].keys())
file_assignments = {}

if uploaded_files:
    st.subheader("Assign each file to a source")
    for i, uf in enumerate(uploaded_files):
        col_file, col_source = st.columns([2, 1])
        with col_file:
            st.write(f"**{uf.name}**")
        with col_source:
            assigned = st.selectbox(
                "Source", source_names,
                key=f"source_{st.session_state.upload_key}_{i}_{uf.name}",
                label_visibility="collapsed")
            file_assignments[uf.name] = {"file": uf, "source": assigned}

    st.write("")
    col_compile, col_clear = st.columns([1, 1])
    with col_compile:
        compile_clicked = st.button("Compile Portfolio", type="primary")
    with col_clear:
        clear_clicked = st.button("Clear All")

    if clear_clicked:
        for key in ["compiled_master", "compile_log", "compile_errors", "price_errors"]:
            st.session_state[key] = [] if key != "compiled_master" else None
        st.session_state.yfinance_error = False
        st.session_state.fetched_prices = {}
        st.session_state.display_rates = None
        st.session_state.upload_key += 1
        st.rerun()

    if compile_clicked:
        st.session_state.compiled_master = None
        st.session_state.compile_log = []
        st.session_state.compile_errors = []
        st.session_state.price_errors = []
        st.session_state.yfinance_error = False
        st.session_state.fetched_prices = {}
        st.session_state.display_rates = rates
        all_data = []
        for fname, assignment in file_assignments.items():
            uf = assignment["file"]
            src_name = assignment["source"]
            src_cfg = sources_config["sources"][src_name]
            parser_name = src_cfg["parser"]
            if parser_name not in PARSERS:
                st.session_state.compile_errors.append(f"{fname}: Parser '{parser_name}' not implemented.")
                continue
            try:
                df = PARSERS[parser_name](uf, src_cfg, mapping_asset_class, mapping_us_situs)
                if df is None or len(df) == 0:
                    st.session_state.compile_errors.append(f"{fname}: No data returned.")
                    continue
                if hasattr(df, "attrs"):
                    if df.attrs.get("yfinance_error"):
                        st.session_state.yfinance_error = True
                    st.session_state.price_errors.extend(df.attrs.get("price_errors", []))
                    st.session_state.fetched_prices.update(df.attrs.get("fetched_prices", {}))
                all_data.append(df)
                st.session_state.compile_log.append(f"{fname} -> {src_name} ({len(df)} items)")
            except Exception as e:
                st.session_state.compile_errors.append(f"{fname}: {e}\n\n{traceback.format_exc()}")
        if all_data:
            master = pd.concat(all_data, ignore_index=True)
            if rates and not fx_error:
                master = convert_to_usd(master, rates)
            master["Broad Asset Class"] = master["Asset Class"].map(broad_ac_map).fillna("Other")
            st.session_state.compiled_master = master
        st.rerun()
else:
    if st.session_state.compiled_master is None:
        st.info("Upload your broker exports and manual file above, or load your previous compilation.")

if st.session_state.compile_log:
    st.subheader("Sources compiled")
    for entry in st.session_state.compile_log:
        st.write(f"✅ {entry}")

if st.session_state.compile_errors:
    st.subheader("Errors")
    for err in st.session_state.compile_errors:
        st.error(err)
    if st.button("Clear errors"):
        st.session_state.compile_errors = []
        st.rerun()

if fx_error and st.session_state.display_rates is None:
    st.error("FX rates could not be retrieved. Balance (USD) values will not be calculated.")
if st.session_state.yfinance_error:
    st.error("yfinance not installed. Run: pip install yfinance")
if st.session_state.price_errors:
    st.warning(f"Stock prices unavailable for: {', '.join(set(st.session_state.price_errors))}")

if not currency_lookthrough.empty:
    wc = currency_lookthrough.groupby("Asset Name")["Weight"].sum()
    for asset, tw in wc[~wc.between(0.999, 1.001)].items():
        st.warning(f"Lookthrough weights for '{asset}' sum to {tw:.3f} (expected 1.000).")

# ============================================================
# SECTION: Compiled Portfolio
# ============================================================
master = st.session_state.compiled_master

if master is not None and len(master) > 0:
    st.header("Compiled Portfolio")

    col_save, col_spacer2 = st.columns([1, 2])
    with col_save:
        if st.button("Save compilation"):
            save_compiled(master, st.session_state.display_rates, st.session_state.fetched_prices)
            st.success(f"Saved {len(master)} items.")

    if "Balance (USD)" in master.columns and master["Balance (USD)"].notna().any():
        st.metric("Total Portfolio (USD)", fmt_k(master["Balance (USD)"].sum()))

    st.subheader("All Holdings")
    display_cols = [
        "Asset Name", "Asset Class", "Broad Asset Class", "Currency",
        "Institution", "Account Type", "Jurisdiction", "Beneficiary",
        "Balance (Local)", "Balance (USD)", "US Situs Flag", "Tag",
    ]
    st.dataframe(
        master[display_cols].style.format({"Balance (Local)": "{:,.2f}", "Balance (USD)": "{:,.2f}"}),
        use_container_width=True)

    # ============================================================
    # SECTION: Allocation Charts
    # ============================================================
    if "Balance (USD)" in master.columns and master["Balance (USD)"].notna().any():
        st.header("Allocation")

        hide_balances = st.toggle(
            "Hide USD amounts", value=False,
            help="Hide USD balance amounts from allocation tables. Percentages remain visible.")

        for attribute, label in [("Broad Asset Class", "Broad Asset Class"), ("Asset Class", "Asset Class")]:
            st.subheader(label)
            fig, legend_html, hidden_html = make_allocation_bar(master, attribute)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                st.markdown(hidden_html if hide_balances else legend_html, unsafe_allow_html=True)

        # Currency
        st.subheader("Currency")
        has_lt = not currency_lookthrough.empty
        lt_on = False
        if has_lt:
            lt_on = st.toggle("Currency look-through", value=False,
                              help="Explode multi-currency assets into underlying currency exposures.")
        if lt_on:
            st.caption("Look-through enabled")
            master_ccy = apply_currency_lookthrough(master, currency_lookthrough)
        else:
            master_ccy = master
        fig, legend_html, hidden_html = make_allocation_bar(master_ccy, "Currency")
        if fig:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.markdown(hidden_html if hide_balances else legend_html, unsafe_allow_html=True)

        for attribute, label in [("Jurisdiction", "Jurisdiction"), ("Institution", "Institution"),
                                 ("Account Type", "Account Type"), ("US Situs Flag", "US Situs")]:
            st.subheader(label)
            fig, legend_html, hidden_html = make_allocation_bar(master, attribute)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                st.markdown(hidden_html if hide_balances else legend_html, unsafe_allow_html=True)

        # PDF download
        st.markdown("---")
        ref_rates_pdf = st.session_state.display_rates if st.session_state.display_rates else rates
        pdf_charts = [
            ("Broad Asset Class", master, "Broad Asset Class"),
            ("Asset Class", master, "Asset Class"),
            ("Currency", master_ccy if lt_on else master, "Currency"),
            ("Jurisdiction", master, "Jurisdiction"),
            ("Institution", master, "Institution"),
            ("Account Type", master, "Account Type"),
            ("US Situs", master, "US Situs Flag"),
        ]
        try:
            pdf_bytes = generate_pdf(master, pdf_charts, ref_rates_pdf, st.session_state.fetched_prices, hide_balances)
            st.download_button(
                label="Download PDF Report",
                data=pdf_bytes,
                file_name=f"asset_allocation_{date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf")
        except ImportError:
            st.warning("PDF export requires reportlab. Run: pip install reportlab")
        except Exception as e:
            st.error(f"PDF generation failed: {e}")

    # ============================================================
    # SECTION: Unmapped Items
    # ============================================================
    unmapped_ac = master[master["Asset Class"] == "UNMAPPED"]
    unmapped_us = master[master["US Situs Flag"] == "UNMAPPED"]

    if len(unmapped_ac) > 0 or len(unmapped_us) > 0:
        st.header("Unmapped Items")
        st.warning("Some items could not be mapped. Add them to mapping tables, then edit the CSVs.")
        if len(unmapped_ac) > 0:
            st.write("**Missing Asset Class mapping:**")
            for name in unmapped_ac["Asset Name"].unique():
                st.write(f"  - {name}")
            st.write("Valid: " + ", ".join(asset_class_labels["Label"].tolist()))
        if len(unmapped_us) > 0:
            st.write("**Missing US Situs Flag mapping:**")
            for name in unmapped_us["Asset Name"].unique():
                st.write(f"  - {name}")
            st.write("Valid: Y, N")

        if st.button("Add unmapped items to mapping tables"):
            added_ac = added_us = 0
            for csv_path, col, flag_col in [
                ("config/mapping_asset_class.csv", "Asset Class", "Asset Class"),
                ("config/mapping_us_situs.csv", "US Situs Flag", "US Situs Flag"),
            ]:
                existing = pd.read_csv(csv_path)
                existing_names = existing["Underlying Instrument Description"].tolist()
                unmapped_names = master[master[flag_col] == "UNMAPPED"]["Asset Name"].unique()
                new_rows = [{"Underlying Instrument Description": n, col: ""} for n in unmapped_names if n not in existing_names]
                if new_rows:
                    pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True).to_csv(csv_path, index=False)
                if col == "Asset Class":
                    added_ac = len(new_rows)
                else:
                    added_us = len(new_rows)
            st.success(f"Added {added_ac} to mapping_asset_class.csv and {added_us} to mapping_us_situs.csv.")

# ============================================================
# SECTION: Reference Data
# ============================================================
st.markdown("---")
st.markdown('<p style="color:#A09080;font-size:18px;font-weight:600;margin-bottom:4px;'
            'font-family:Avenir Next,Avenir,-apple-system,BlinkMacSystemFont,sans-serif;">Reference Data</p>', unsafe_allow_html=True)

ref_rates = st.session_state.display_rates if st.session_state.display_rates else rates
col_fx, col_prices, col_classes = st.columns(3)

with col_fx:
    st.markdown('<p style="color:#A09080;font-size:14px;font-weight:600;'
                'font-family:Source Sans Pro,sans-serif;">FX Rates</p>', unsafe_allow_html=True)
    if ref_rates and len(ref_rates) > 1:
        fx_rows = [[f"{ccy}/USD", f"{1/ref_rates[ccy]:.4f}"] for ccy in ["GBP", "EUR", "SGD", "AUD", "HKD", "JPY"] if ccy in ref_rates]
        if fx_rows:
            st.markdown(make_grey_table(["Pair", "Rate"], fx_rows), unsafe_allow_html=True)
    else:
        st.markdown('<p style="color:#A09080;font-size:13px;">FX rates unavailable</p>', unsafe_allow_html=True)

with col_prices:
    st.markdown('<p style="color:#A09080;font-size:14px;font-weight:600;'
                'font-family:Source Sans Pro,sans-serif;">Stock Prices</p>', unsafe_allow_html=True)
    if st.session_state.fetched_prices:
        st.markdown(make_grey_table(["Ticker", "Price"],
            [[t, f"{p:,.4f}"] for t, p in sorted(st.session_state.fetched_prices.items())]), unsafe_allow_html=True)
    else:
        st.markdown('<p style="color:#A09080;font-size:13px;">No stock prices fetched yet.</p>', unsafe_allow_html=True)

with col_classes:
    st.markdown('<p style="color:#A09080;font-size:14px;font-weight:600;'
                'font-family:Source Sans Pro,sans-serif;">Valid Asset Classes</p>', unsafe_allow_html=True)
    st.markdown(make_grey_table(["Asset Class"], [[r["Label"]] for _, r in asset_class_labels.iterrows()]), unsafe_allow_html=True)
