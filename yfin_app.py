import os
import io
import glob
import zipfile
from datetime import date, timedelta
import pandas as pd
import streamlit as st
import yfinance as yf

# Configure Streamlit page settings
st.set_page_config(
    page_title="Stock Screener & Market Data Downloader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling for modern aesthetic
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.02rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .stMetric {
        background-color: #F8FAFC;
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid #E2E8F0;
    }
    .success-box {
        background-color: #ECFDF5;
        border: 1px solid #A7F3D0;
        color: #065F46;
        padding: 12px 16px;
        border-radius: 8px;
        margin: 10px 0;
    }
    .filter-box {
        background-color: #F0F9FF;
        border: 1px solid #BAE6FD;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 15px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Server Storage Directory for downloaded CSV files
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Main Title Header
st.markdown('<div class="main-title">📈 Stock Screener & Yahoo Finance Exporter</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Download stock data from yfinance, save to server storage, and run custom Moving Average bulk screening logic!</div>',
    unsafe_allow_html=True,
)

# Sidebar Configuration
st.sidebar.header("⚙️ Global Date & Data Settings")

today = date.today()
default_start = today - timedelta(days=365)

col_s1, col_s2 = st.sidebar.columns(2)
start_date = col_s1.date_input("Start Date", value=default_start)
end_date = col_s2.date_input("End Date", value=today)

interval = st.sidebar.selectbox(
    "Interval",
    options=["1d", "1wk", "1mo"],
    index=0,
    format_func=lambda x: {"1d": "Daily", "1wk": "Weekly", "1mo": "Monthly"}[x],
    help="Select the frequency of historical data points",
)

st.sidebar.divider()
st.sidebar.caption("💾 **Server Storage Status**")
server_csvs = glob.glob(os.path.join(DOWNLOADS_DIR, "*.csv"))
st.sidebar.info(f"📁 **{len(server_csvs)}** CSV files currently cached in server folder:\n`{DOWNLOADS_DIR}`")


# Helper function: Fetch and format historical data for a single symbol
def fetch_and_clean_data(ticker_symbol: str, start: date, end: date, freq: str):
    adjusted_end = end + timedelta(days=1)
    try:
        df = yf.download(
            tickers=ticker_symbol,
            start=start.strftime("%Y-%m-%d"),
            end=adjusted_end.strftime("%Y-%m-%d"),
            interval=freq,
            progress=False,
            auto_adjust=False,
        )
    except Exception:
        return None

    if df is None or df.empty:
        return None

    data = df.copy()

    # Flatten MultiIndex columns if present
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]

    # Ensure required columns exist
    if "Close" not in data.columns:
        return None

    # Round all float values to 2 decimal places
    data = data.round(2)

    # Ensure index has name 'Date' and reset into column
    if not data.index.name:
        data.index.name = "Date"
    data_reset = data.reset_index()

    # Format Date column for clean presentation
    if "Date" in data_reset.columns and pd.api.types.is_datetime64_any_dtype(data_reset["Date"]):
        data_reset["Date"] = data_reset["Date"].dt.strftime("%Y-%m-%d")

    return data_reset, data


# Helper function to save df to server CSV
def save_data_to_server(df_reset: pd.DataFrame, symbol: str, start: date, end: date, freq: str):
    safe_sym = "".join(c for c in symbol if c.isalnum() or c in ("-", "_", ".")).rstrip()
    filename = f"{safe_sym}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}_{freq}.csv"
    filepath = os.path.join(DOWNLOADS_DIR, filename)
    csv_str = df_reset.to_csv(index=False, float_format="%.2f")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(csv_str)
    return filename, filepath, csv_str


# Helper function: Extract symbols list from uploaded file
def extract_symbols_from_file(uploaded_file):
    try:
        if uploaded_file.name.lower().endswith((".xlsx", ".xls")):
            input_df = pd.read_excel(uploaded_file)
        else:
            try:
                input_df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                input_df = pd.read_csv(uploaded_file, encoding="latin1")

        input_df.columns = [str(c).strip() for c in input_df.columns]
        
        # Find symbol column
        candidate_cols = [c for c in input_df.columns if c.strip().lower() == "symbol"]
        symbol_col = candidate_cols[0] if candidate_cols else input_df.columns[0]

        raw_symbols = input_df[symbol_col].dropna().astype(str).str.strip().tolist()
        raw_symbols = [s for s in raw_symbols if s]

        processed = []
        for s in raw_symbols:
            u_s = s.upper()
            if not u_s.endswith(".NS") and not u_s.startswith("^") and "-" not in u_s and "." not in u_s:
                # Add default .NS for NSE ticker symbols without extension
                u_s = f"{u_s}.NS"
            processed.append((s, u_s))
        return processed, input_df
    except Exception as e:
        st.error(f"❌ Error reading file: {e}")
        return [], None


# Create Navigation Tabs
tab_screener, tab_batch, tab_single = st.tabs([
    "🎯 Bulk Moving Average Screener",
    "📁 Bulk CSV Downloader & Server Storage",
    "🔍 Single Symbol Downloader",
])

# ==========================================
# TAB 1: BULK MOVING AVERAGE SCREENER
# ==========================================
with tab_screener:
    st.subheader("⚡ Bulk Stock Screener using Moving Average")
    st.write(
        "Screen stocks using your custom Moving Average condition. "
        "Upload a bulk list of stocks, choose your Moving Average period, target value, and operator (`>`, `<`, `=`)."
    )

    # Screener Input Controls
    st.markdown('<div class="filter-box"><b>🔧 Screener Condition Configuration</b></div>', unsafe_allow_html=True)
    
    col_c1, col_c2, col_c3, col_c4 = st.columns(4)

    with col_c1:
        ma_period = st.number_input(
            "Moving Average Window (Days/Bars)",
            min_value=2,
            max_value=500,
            value=20,
            step=1,
            help="Number of periods to compute moving average (e.g. 20, 50, 200)",
        )

    with col_c2:
        ma_type = st.selectbox(
            "MA Type",
            options=["SMA (Simple)", "EMA (Exponential)"],
            index=0,
        )

    with col_c3:
        compare_mode = st.selectbox(
            "Comparison Metric",
            options=[
                "Latest Close Price vs MA Value",
                "Latest MA Value vs User Input Target",
                "Latest Close Price vs User Input Target",
            ],
            index=0,
            help="Choose what value is being compared against what",
        )

    with col_c4:
        operator_choice = st.selectbox(
            "Condition Operator",
            options=["Greater Than ( > )", "Less Than ( < )", "Equal To ( = )"],
            index=0,
            help="Select the filter logic",
        )

    col_v1, col_v2 = st.columns(2)
    with col_v1:
        if "User Input Target" in compare_mode:
            target_user_val = st.number_input(
                "User Input Target Value",
                value=100.0,
                step=1.0,
                help="The numeric threshold value to test against",
            )
        else:
            target_user_val = None
            st.info("💡 Mode evaluates: **Close Price** vs **Moving Average Value** for each stock.")

    with col_v2:
        tolerance_pct = st.number_input(
            "Equal To Tolerance (%)",
            min_value=0.0,
            max_value=10.0,
            value=0.5,
            step=0.1,
            help="Allowed percentage difference for 'Equal To' condition (e.g. 0.5% tolerance)",
        )

    st.markdown("---")
    st.subheader("📂 Stock Selection Source for Screening")

    source_option = st.radio(
        "Choose Bulk Data Source:",
        ["Bulk CSV Upload", "Use Server-Saved CSV Files in `downloads/`"],
        index=0,
        horizontal=True,
    )

    symbols_to_screen = []
    use_server_cache = False

    if source_option == "Bulk CSV Upload":
        u_col1, u_col2 = st.columns([3, 1])
        with u_col1:
            screener_file = st.file_uploader(
                "Upload Bulk Symbols File (CSV / XLSX with 'Symbol' column)",
                type=["csv", "xlsx", "xls"],
                key="screener_file_uploader",
            )
        with u_col2:
            st.write("Sample Template:")
            sample_screener_csv = "Symbol\nRELIANCE.NS\nTCS.NS\nINFY.NS\nHDFCBANK.NS\nICICIBANK.NS\nSBIN.NS\nBHARTIARTL.NS\nITC.NS\nLTIM.NS\nTATAMOTORS.NS\n"
            st.download_button(
                label="📄 Download Sample CSV",
                data=sample_screener_csv,
                file_name="screener_sample.csv",
                mime="text/csv",
                width="stretch",
            )

        if screener_file is not None:
            extracted, _ = extract_symbols_from_file(screener_file)
            symbols_to_screen = [item[1] for item in extracted]
            st.success(f"Loaded **{len(symbols_to_screen)}** symbols from uploaded file.")
    else:
        use_server_cache = True
        server_files = glob.glob(os.path.join(DOWNLOADS_DIR, "*.csv"))
        if not server_files:
            st.warning("⚠️ No CSV files found on server downloads directory. Please download some data in Tab 2 or Tab 3 first, or upload a CSV file above!")
        else:
            st.info(f"Found **{len(server_files)}** saved CSV files in server storage directory.")

    if start_date > end_date:
        st.error("⚠️ Error: **Start Date** cannot be later than **End Date**.")
    else:
        run_screener_btn = st.button("🔍 Run Bulk Stock Screener", type="primary", width="stretch")

        if run_screener_btn:
            if not use_server_cache and not symbols_to_screen:
                st.error("❌ Please upload a CSV file containing stock symbols or select server-saved files.")
            else:
                progress_bar = st.progress(0)
                status_placeholder = st.empty()
                results = []

                if use_server_cache:
                    server_files = glob.glob(os.path.join(DOWNLOADS_DIR, "*.csv"))
                    total_items = len(server_files)

                    for idx, fpath in enumerate(server_files):
                        fname = os.path.basename(fpath)
                        status_placeholder.info(f"⏳ Processing server file ({idx+1}/{total_items}): **{fname}**...")
                        try:
                            df_cached = pd.read_csv(fpath)
                            sym = fname.split("_")[0]

                            if "Close" in df_cached.columns and len(df_cached) >= ma_period:
                                close_series = df_cached["Close"].astype(float)
                                if "EMA" in ma_type:
                                    ma_series = close_series.ewm(span=ma_period, adjust=False).mean()
                                else:
                                    ma_series = close_series.rolling(window=ma_period).mean()

                                latest_close = float(close_series.iloc[-1])
                                latest_ma = float(ma_series.iloc[-1])

                                # Determine values for comparison
                                if compare_mode == "Latest Close Price vs MA Value":
                                    val_a, val_b = latest_close, latest_ma
                                    label_a, label_b = "Latest Close", f"{ma_period}-MA"
                                elif compare_mode == "Latest MA Value vs User Input Target":
                                    val_a, val_b = latest_ma, float(target_user_val)
                                    label_a, label_b = f"Latest {ma_period}-MA", "Target Value"
                                else:
                                    val_a, val_b = latest_close, float(target_user_val)
                                    label_a, label_b = "Latest Close", "Target Value"

                                # Check condition
                                match = False
                                diff = val_a - val_b
                                diff_pct = abs(diff / val_b) * 100 if val_b != 0 else 0

                                if "Greater Than" in operator_choice:
                                    match = val_a > val_b
                                elif "Less Than" in operator_choice:
                                    match = val_a < val_b
                                else:
                                    match = diff_pct <= tolerance_pct

                                results.append({
                                    "Symbol": sym,
                                    "Status": "✅ Pass" if match else "❌ Fail",
                                    "Match": match,
                                    "Latest Close": round(latest_close, 2),
                                    f"{ma_period}-{ma_type[:3]} Value": round(latest_ma, 2),
                                    "Compared Value A": round(val_a, 2),
                                    "Compared Value B": round(val_b, 2),
                                    "Condition": f"{label_a} {operator_choice.split()[0]} {label_b}",
                                    "Data Source": "Server CSV",
                                })
                            else:
                                results.append({
                                    "Symbol": sym,
                                    "Status": f"⚠️ Insufficient rows (<{ma_period})",
                                    "Match": False,
                                    "Latest Close": None,
                                    f"{ma_period}-{ma_type[:3]} Value": None,
                                    "Compared Value A": None,
                                    "Compared Value B": None,
                                    "Condition": "-",
                                    "Data Source": "Server CSV",
                                })
                        except Exception as e:
                            results.append({
                                "Symbol": fname,
                                "Status": f"❌ Error: {e}",
                                "Match": False,
                                "Latest Close": None,
                                f"{ma_period}-{ma_type[:3]} Value": None,
                                "Compared Value A": None,
                                "Compared Value B": None,
                                "Condition": "-",
                                "Data Source": "Server CSV",
                            })
                        progress_bar.progress((idx + 1) / total_items)

                else:
                    total_items = len(symbols_to_screen)
                    for idx, sym in enumerate(symbols_to_screen):
                        status_placeholder.info(f"⏳ Fetching & Screening ({idx+1}/{total_items}): **{sym}**...")
                        try:
                            res = fetch_and_clean_data(sym, start_date, end_date, interval)
                            if res is not None:
                                df_reset, df_raw = res
                                # Save to server for caching & testing purpose
                                save_data_to_server(df_reset, sym, start_date, end_date, interval)

                                if "Close" in df_raw.columns and len(df_raw) >= ma_period:
                                    close_series = df_raw["Close"].astype(float)
                                    if "EMA" in ma_type:
                                        ma_series = close_series.ewm(span=ma_period, adjust=False).mean()
                                    else:
                                        ma_series = close_series.rolling(window=ma_period).mean()

                                    latest_close = float(close_series.iloc[-1])
                                    latest_ma = float(ma_series.iloc[-1])

                                    if compare_mode == "Latest Close Price vs MA Value":
                                        val_a, val_b = latest_close, latest_ma
                                        label_a, label_b = "Latest Close", f"{ma_period}-MA"
                                    elif compare_mode == "Latest MA Value vs User Input Target":
                                        val_a, val_b = latest_ma, float(target_user_val)
                                        label_a, label_b = f"Latest {ma_period}-MA", "Target Value"
                                    else:
                                        val_a, val_b = latest_close, float(target_user_val)
                                        label_a, label_b = "Latest Close", "Target Value"

                                    diff = val_a - val_b
                                    diff_pct = abs(diff / val_b) * 100 if val_b != 0 else 0

                                    if "Greater Than" in operator_choice:
                                        match = val_a > val_b
                                    elif "Less Than" in operator_choice:
                                        match = val_a < val_b
                                    else:
                                        match = diff_pct <= tolerance_pct

                                    results.append({
                                        "Symbol": sym,
                                        "Status": "✅ Pass" if match else "❌ Fail",
                                        "Match": match,
                                        "Latest Close": round(latest_close, 2),
                                        f"{ma_period}-{ma_type[:3]} Value": round(latest_ma, 2),
                                        "Compared Value A": round(val_a, 2),
                                        "Compared Value B": round(val_b, 2),
                                        "Condition": f"{label_a} {operator_choice.split()[0]} {label_b}",
                                        "Data Source": "yfinance API (Saved to Server)",
                                    })
                                else:
                                    results.append({
                                        "Symbol": sym,
                                        "Status": f"⚠️ Insufficient rows (<{ma_period})",
                                        "Match": False,
                                        "Latest Close": None,
                                        f"{ma_period}-{ma_type[:3]} Value": None,
                                        "Compared Value A": None,
                                        "Compared Value B": None,
                                        "Condition": "-",
                                        "Data Source": "yfinance API",
                                    })
                            else:
                                results.append({
                                    "Symbol": sym,
                                    "Status": "⚠️ No Data from Yahoo Finance",
                                    "Match": False,
                                    "Latest Close": None,
                                    f"{ma_period}-{ma_type[:3]} Value": None,
                                    "Compared Value A": None,
                                    "Compared Value B": None,
                                    "Condition": "-",
                                    "Data Source": "yfinance API",
                                })
                        except Exception as e:
                            results.append({
                                "Symbol": sym,
                                "Status": f"❌ Error: {e}",
                                "Match": False,
                                "Latest Close": None,
                                f"{ma_period}-{ma_type[:3]} Value": None,
                                "Compared Value A": None,
                                "Compared Value B": None,
                                "Condition": "-",
                                "Data Source": "yfinance API",
                            })

                        progress_bar.progress((idx + 1) / total_items)

                status_placeholder.empty()

                if results:
                    res_df = pd.DataFrame(results)
                    passed_df = res_df[res_df["Match"] == True]
                    failed_df = res_df[res_df["Match"] == False]

                    st.markdown(
                        f'<div class="success-box">🎉 <b>Screening Completed!</b> Found <b>{len(passed_df)}</b> stocks out of <b>{len(res_df)}</b> matching your criteria.</div>',
                        unsafe_allow_html=True,
                    )

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total Stocks Screened", len(res_df))
                    m2.metric("Matched / Passed Filter", len(passed_df))
                    m3.metric("Excluded / Failed Filter", len(failed_df))

                    # Download filtered results as CSV
                    passed_csv = passed_df.to_csv(index=False, float_format="%.2f").encode("utf-8")
                    st.download_button(
                        label=f"⬇️ Download Filtered Stock List ({len(passed_df)} Stocks) as CSV",
                        data=passed_csv,
                        file_name=f"Screened_Stocks_MA{ma_period}_{date.today().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        type="primary",
                        width="stretch",
                    )

                    # Display Filtered Results Table
                    st.subheader("🎯 Filtered Stocks List (Passed Condition)")
                    if not passed_df.empty:
                        st.dataframe(passed_df.drop(columns=["Match"]), width="stretch", hide_index=True)
                    else:
                        st.warning("No stocks matched the selected screening condition.")

                    # Full Summary Table
                    with st.expander("📊 View Complete Screening Results (All Stocks)", expanded=False):
                        st.dataframe(res_df.drop(columns=["Match"]), width="stretch", hide_index=True)


# ==========================================
# TAB 2: BULK CSV DOWNLOADER & SERVER STORAGE
# ==========================================
with tab_batch:
    st.subheader("📁 Bulk Stock Data Downloader & Server Storage")
    st.write(
        "Upload a CSV file containing a **`Symbol`** column. "
        "The app will fetch historical data from Yahoo Finance (auto appending `.NS` for Indian symbols if needed), "
        "save all individual CSV files to server storage (`downloads/`), and provide a **ZIP** package for download."
    )

    col_up1, col_up2 = st.columns([3, 1])
    with col_up1:
        uploaded_file = st.file_uploader(
            "Upload CSV or Excel File (must contain 'Symbol' column)",
            type=["csv", "xlsx", "xls"],
            key="batch_file_uploader",
        )
    with col_up2:
        st.write("Need a template?")
        sample_csv = (
            "Company Name,Industry,Symbol,Series,ISIN Code\n"
            "Adani Enterprises Ltd.,Metals & Mining,ADANIENT,EQ,INE423A01024\n"
            "Bajaj Auto Ltd.,Automobile and Auto Components,BAJAJ-AUTO,EQ,INE917I01010\n"
            "HDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034\n"
            "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\n"
            "Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029\n"
        )
        st.download_button(
            label="📄 Download Sample CSV",
            data=sample_csv,
            file_name="sample_symbols.csv",
            mime="text/csv",
            width="stretch",
        )

    if uploaded_file is not None:
        processed_symbols, _ = extract_symbols_from_file(uploaded_file)

        if not processed_symbols:
            st.error("❌ No valid symbols found in the uploaded file.")
        else:
            st.info(f"📋 Found **{len(processed_symbols)}** symbols to process.")

            with st.expander("👁️ View Preview of Symbols to Fetch", expanded=False):
                preview_df = pd.DataFrame(processed_symbols, columns=["Original Symbol", "Queried Symbol"])
                st.dataframe(preview_df, width="stretch", hide_index=True)

            if start_date > end_date:
                st.error("⚠️ Error: **Start Date** cannot be later than **End Date**.")
            else:
                start_batch = st.button("🚀 Fetch Data & Save to Server + ZIP Export", type="primary", width="stretch")

                if start_batch:
                    progress_bar = st.progress(0)
                    status_placeholder = st.empty()
                    results_summary = []
                    successful_files = {}

                    zip_buffer = io.BytesIO()

                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                        total_count = len(processed_symbols)

                        for idx, (orig_sym, ns_sym) in enumerate(processed_symbols):
                            status_placeholder.info(f"⏳ ({idx + 1}/{total_count}) Fetching data for **{ns_sym}**...")

                            try:
                                res = fetch_and_clean_data(ns_sym, start_date, end_date, interval)
                                if res is not None:
                                    data_reset, _ = res
                                    row_count = len(data_reset)

                                    csv_filename, local_path, csv_string = save_data_to_server(
                                        data_reset, ns_sym, start_date, end_date, interval
                                    )

                                    zip_file.writestr(csv_filename, csv_string)

                                    successful_files[ns_sym] = data_reset
                                    results_summary.append({
                                        "Original Symbol": orig_sym,
                                        "Queried Symbol": ns_sym,
                                        "Status": "✅ Success",
                                        "Records": row_count,
                                        "Server File": csv_filename,
                                    })
                                else:
                                    results_summary.append({
                                        "Original Symbol": orig_sym,
                                        "Queried Symbol": ns_sym,
                                        "Status": "⚠️ No Data",
                                        "Records": 0,
                                        "Server File": "-",
                                    })
                            except Exception as err:
                                results_summary.append({
                                    "Original Symbol": orig_sym,
                                    "Queried Symbol": ns_sym,
                                    "Status": f"❌ Error: {err}",
                                    "Records": 0,
                                    "Server File": "-",
                                })

                            progress_bar.progress((idx + 1) / total_count)

                    status_placeholder.empty()
                    zip_buffer.seek(0)
                    zip_bytes = zip_buffer.getvalue()

                    zip_filename = f"Stock_Data_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}_{interval}.zip"
                    local_zip_path = os.path.join(DOWNLOADS_DIR, zip_filename)
                    with open(local_zip_path, "wb") as zf:
                        zf.write(zip_bytes)

                    success_count = sum(1 for r in results_summary if "Success" in r["Status"])
                    fail_count = total_count - success_count

                    st.markdown(
                        f'<div class="success-box">🎉 <b>Bulk Processing Completed!</b> All CSV files saved to server storage (<code>{DOWNLOADS_DIR}</code>) and zipped.</div>',
                        unsafe_allow_html=True,
                    )

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total Symbols Processed", total_count)
                    m2.metric("Successfully Downloaded", success_count)
                    m3.metric("Failed / No Data", fail_count)

                    st.download_button(
                        label=f"⬇️ Download All ({success_count} CSVs) as ZIP File",
                        data=zip_bytes,
                        file_name=zip_filename,
                        mime="application/zip",
                        type="primary",
                        width="stretch",
                    )

                    st.subheader("📊 Processing Summary")
                    summary_df = pd.DataFrame(results_summary)
                    st.dataframe(summary_df, width="stretch", hide_index=True)


# ==========================================
# TAB 3: SINGLE SYMBOL SEARCH & DOWNLOAD
# ==========================================
with tab_single:
    st.subheader("🔍 Single Script Ticker Lookup & Download")
    st.write("Fetch historical data for any single ticker symbol, download its CSV, and save to server storage.")

    col_q1, col_q2 = st.columns([1, 2])
    with col_q1:
        quick_symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "^NSEI", "BTC-USD"]
        selected_quick = st.selectbox("⚡ Quick Pick", ["Custom"] + quick_symbols)

    with col_q2:
        symbol_default = selected_quick if selected_quick != "Custom" else "RELIANCE.NS"
        single_symbol = st.text_input(
            "Script Symbol (e.g. RELIANCE.NS, AAPL)",
            value=symbol_default,
            help="Enter ticker symbol (add .NS for Indian stocks)",
        ).strip().upper()

    fetch_single_btn = st.button("📥 Fetch Symbol Data & Save CSV", type="primary", width="stretch")

    if fetch_single_btn:
        if not single_symbol:
            st.info("👈 Please enter a Script / Ticker Symbol.")
        elif start_date > end_date:
            st.error("⚠️ Error: **Start Date** cannot be later than **End Date**.")
        else:
            with st.spinner(f"Fetching data for **{single_symbol}**..."):
                try:
                    single_res = fetch_and_clean_data(single_symbol, start_date, end_date, interval)
                except Exception as e:
                    st.error(f"❌ Error while fetching data: {e}")
                    single_res = None

            if single_res is not None:
                data_reset, data = single_res

                # Save to server storage
                single_filename, local_filepath, csv_str = save_data_to_server(
                    data_reset, single_symbol, start_date, end_date, interval
                )
                csv_bytes = csv_str.encode("utf-8")

                # Metrics Overview
                st.subheader(f"📌 Summary for {single_symbol}")
                m_col1, m_col2, m_col3, m_col4 = st.columns(4)

                if "Close" in data.columns and len(data) > 0:
                    first_close = round(float(data["Close"].iloc[0]), 2)
                    last_close = round(float(data["Close"].iloc[-1]), 2)
                    net_change = round(last_close - first_close, 2)
                    pct_change = round((net_change / first_close) * 100, 2)

                    curr = "₹" if single_symbol.endswith(".NS") or single_symbol.endswith(".BO") else "$"
                    m_col1.metric("Latest Close", f"{curr}{last_close:,.2f}", delta=f"{net_change:+,.2f} ({pct_change:+.2f}%)")

                    if "High" in data.columns and "Low" in data.columns:
                        period_high = round(float(data["High"].max()), 2)
                        period_low = round(float(data["Low"].min()), 2)
                        m_col2.metric("Period High", f"{curr}{period_high:,.2f}")
                        m_col3.metric("Period Low", f"{curr}{period_low:,.2f}")

                m_col4.metric("Total Records", f"{len(data)} rows")

                # Chart
                st.subheader("📈 Price Chart (Close)")
                if "Close" in data.columns:
                    st.line_chart(data["Close"], width="stretch")

                # Export section
                st.subheader("💾 CSV Download & Storage")
                down_col1, down_col2 = st.columns([1, 2])
                with down_col1:
                    st.download_button(
                        label="⬇️ Download CSV File",
                        data=csv_bytes,
                        file_name=single_filename,
                        mime="text/csv",
                        type="primary",
                        width="stretch",
                    )
                with down_col2:
                    st.success(f"✅ CSV saved on server disk: `{local_filepath}`")

                # Data Preview
                st.dataframe(data_reset, width="stretch", hide_index=True)

            else:
                st.warning(
                    f"⚠️ No data found for **{single_symbol}** between **{start_date}** and **{end_date}**."
                )
