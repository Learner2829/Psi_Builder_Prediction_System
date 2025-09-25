# import yfinance as yf
# import pandas as pd

# ticker = 'TCS.NS'

# data = yf.download(ticker, interval='1h', period='2y')

# # Flatten MultiIndex columns if any
# if isinstance(data.columns, pd.MultiIndex):
#     data.columns = [' '.join(col).strip() for col in data.columns.values]

# # Reset index to get datetime as column
# data.reset_index(inplace=True)

# # Convert datetime to string for Excel
# data['Datetime'] = data['Datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')

# # Save to Excel without index
# data.to_excel('tcs_1h_data.xlsx', index=False)

# print("✅ Saved 1-hour TCS data to 'tcs_1h_data.xlsx'")
# print(data.head())

# import pandas as pd

# # Load your CSV file (change filename accordingly)
# df = pd.read_csv("TCS_1h_10yr.csv")
# print(df.columns)



# # Ensure Datetime column is in datetime format
# df['date'] = pd.to_datetime(df['date'])

# # Sort by datetime just in case
# df = df.sort_values('date')

# # VWAP calculation requires (High + Low + Close) / 3 as Typical Price
# df['TypicalPrice'] = (df['High TCS.NS'] + df['Low TCS.NS'] + df['Close TCS.NS']) / 3

# print(df.columns)

# # Multiply Typical Price with Volume
# df['TPxVolume'] = df['TypicalPrice'] * df['Volume TCS.NS']

# # Resample to hourly frequency and compute VWAP
# def vwap(group):
#     return group['TPxVolume'].sum() / group['Volume TCS.NS'].sum()

# # Group by each hour
# vwap_hourly = df.set_index('date').groupby(pd.Grouper(freq='1H')).apply(vwap)

# # Assign VWAP back to original dataframe (forward fill per hour)
# df['VWAP_1H'] = df.set_index('date').index.floor('H').map(vwap_hourly)

# # Save to new CSV
# df.to_csv("stock_with_vwap.csv", index=False)

# print("VWAP column added and saved to stock_with_vwap.csv")



# # vwap.py
# import pandas as pd
# import matplotlib.pyplot as plt
# import os
# import sys
# from pathlib import Path

# # ---------- CONFIG ----------
# # default input filename (change if your file name differs)
# DEFAULT_FILENAME = "TCS_1h_10yr.csv"
# OUT_CSV = "TCS_1h_10yr.csv"

# OUT_PLOT = "vwap_plot.png"
# # ----------------------------

# def find_column(cols, keywords):
#     """Return first column from cols that contains any keyword (case-insensitive)."""
#     for kw in keywords:
#         for c in cols:
#             if kw.lower() in c.lower():
#                 return c
#     return None

# def main():
#     filename = "TCS_1h_10yr.csv"
#     # allow passing file path as first arg
#     if len(sys.argv) > 1:
#         filename = sys.argv[1]

#     p = Path(filename)
#     if not p.exists():
#         raise FileNotFoundError("CSV file not found at: {}. Place CSV in script folder or supply path as argument.".format(p))

#     # read csv
#     df = pd.read_csv(p, low_memory=False)

#     # print columns for debugging (like you saw earlier)
#     print(list(df.columns))

#     # find datetime column (common names)
#     dt_col = find_column(df.columns, ["date", "datetime", "time", "timestamp"])
#     if dt_col is None:
#         # fallback: assume first column is datetime
#         dt_col = df.columns[0]

#     # parse datetime
#     df[dt_col] = pd.to_datetime(df[dt_col], infer_datetime_format=True, errors='coerce')
#     if df[dt_col].isna().all():
#         raise ValueError("Could not parse any datetime values from column: {}".format(dt_col))

#     # set index
#     df = df.sort_values(dt_col).set_index(dt_col)

#     # detect price & volume columns
#     high_col = find_column(df.columns, ["high", "h"])
#     low_col  = find_column(df.columns, ["low", "l"])
#     close_col = find_column(df.columns, ["close", "c", "last", "price"])
#     vol_col = find_column(df.columns, ["volume", "vol", "v"])

#     if not (high_col and low_col and close_col and vol_col):
#         raise ValueError("Could not find required columns. Detected - high: {}, low: {}, close: {}, volume: {}.\nColumns present: {}"
#                          .format(high_col, low_col, close_col, vol_col, ", ".join(df.columns)))

#     # convert to numeric
#     df[high_col]  = pd.to_numeric(df[high_col], errors='coerce')
#     df[low_col]   = pd.to_numeric(df[low_col], errors='coerce')
#     df[close_col] = pd.to_numeric(df[close_col], errors='coerce')
#     df[vol_col]   = pd.to_numeric(df[vol_col], errors='coerce')

#     # Typical price and TP*V
#     df["TypicalPrice"] = (df[high_col] + df[low_col] + df[close_col]) / 3.0
#     df["TPxV"] = df["TypicalPrice"] * df[vol_col]

#     # hourly VWAP (group by hour)
#     hourly_vwap = df.groupby(pd.Grouper(freq="1H")).apply(
#         lambda g: (g["TPxV"].sum() / g[vol_col].sum()) if g[vol_col].sum() != 0 else float("nan")
#     )

#     # map hourly VWAP back to each row
#     df["VWAP_1H"] = df.index.floor("H").map(hourly_vwap)

#     # save CSV (keep original columns + VWAP_1H)
#     # create output df: put VWAP_1H as a new column in original order (but index is datetime)
#     out_df = df.copy()
#     out_df.to_csv(OUT_CSV, index=True)
#     print("Saved CSV with VWAP to:", OUT_CSV)

#     # Prepare plotting dataframe
#     plot_df = out_df[[close_col, "VWAP_1H"]].dropna(how="all")

#     # Detect crossovers: close crosses above VWAP (bullish) and crosses below (bearish)
#     s_close = plot_df[close_col]
#     s_vwap = plot_df["VWAP_1H"]

#     # create boolean series where close > vwap
#     above = s_close > s_vwap
#     cross_up = (~above.shift(1).fillna(False)) & (above.fillna(False))   # False->True
#     cross_down = (above.shift(1).fillna(False)) & (~above.fillna(False)) # True->False

#     # plot
#     fig, ax = plt.subplots(figsize=(14, 7))
#     ax.plot(plot_df.index, plot_df[close_col], label="Close ({})".format(close_col), linewidth=1.0)
#     ax.plot(plot_df.index, plot_df["VWAP_1H"], label="VWAP (hourly)", linewidth=1.5)

#     # mark crossovers
#     ax.scatter(plot_df.index[cross_up], plot_df[close_col][cross_up], marker="^", s=80, label="Cross Above (Bullish)", zorder=5)
#     ax.scatter(plot_df.index[cross_down], plot_df[close_col][cross_down], marker="v", s=80, label="Cross Below (Bearish)", zorder=5)

#     ax.set_title("Close Price vs Hourly VWAP")
#     ax.set_xlabel("Datetime")
#     ax.set_ylabel("Price")
#     ax.legend()
#     ax.grid(True)
#     plt.tight_layout()

#     # save plot
#     plt.savefig(OUT_PLOT, dpi=150)
#     print("Saved plot to:", OUT_PLOT)
#     plt.show()

# if __name__ == "__main__":
#     main()


# vwap.py (robust save fallback for PermissionError)
import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
from pathlib import Path
import datetime
import tempfile

# ---------- CONFIG ----------
DEFAULT_FILENAME = "TCS_1h_10yr.csv"   # input CSV (change or pass as arg)
OUT_CSV = "TCS_1h_10yr.csv"       # preferred output CSV
OUT_PLOT = "vwap_plot.png"
# ----------------------------

def find_column(cols, keywords):
    for kw in keywords:
        for c in cols:
            if kw.lower() in c.lower():
                return c
    return None

def safe_save_csv(df, preferred_path: Path):
    """Try saving to preferred_path; on PermissionError, try timestamped fallback in same dir,
       then temp dir. Returns actual saved Path or raises."""
    try:
        df.to_csv(preferred_path, index=True)
        return preferred_path
    except PermissionError:
        # First fallback: timestamped filename in same directory
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_name = preferred_path.with_name(preferred_path.stem + "_" + ts + preferred_path.suffix)
        try:
            df.to_csv(fallback_name, index=True)
            return fallback_name
        except PermissionError:
            # Final fallback: write into system temp directory
            temp_dir = Path(tempfile.gettempdir())
            fallback_temp = temp_dir / fallback_name.name
            df.to_csv(fallback_temp, index=True)
            return fallback_temp

def main():
    filename = DEFAULT_FILENAME
    if len(sys.argv) > 1:
        filename = sys.argv[1]

    p = Path(filename)
    if not p.exists():
        raise FileNotFoundError(f"CSV file not found at: {p}. Place CSV in script folder or supply path as argument.")

    df = pd.read_csv(p, low_memory=False)
    print(list(df.columns))

    # detect datetime column
    dt_col = find_column(df.columns, ["date", "datetime", "time", "timestamp"]) or df.columns[0]
    # parse datetime (removed deprecated infer_datetime_format usage)
    df[dt_col] = pd.to_datetime(df[dt_col], errors='coerce')
    if df[dt_col].isna().all():
        raise ValueError(f"Could not parse any datetime values from column: {dt_col}")

    df = df.sort_values(dt_col).set_index(dt_col)

    # detect price/volume columns
    high_col = find_column(df.columns, ["high", "h"])
    low_col = find_column(df.columns, ["low", "l"])
    close_col = find_column(df.columns, ["close", "c", "last", "price"])
    vol_col = find_column(df.columns, ["volume", "vol", "v"])

    if not (high_col and low_col and close_col and vol_col):
        raise ValueError("Could not find required columns. Detected - high: {}, low: {}, close: {}, volume: {}.\nColumns present: {}"
                         .format(high_col, low_col, close_col, vol_col, ", ".join(df.columns)))

    # convert to numeric
    df[high_col]  = pd.to_numeric(df[high_col], errors='coerce')
    df[low_col]   = pd.to_numeric(df[low_col], errors='coerce')
    df[close_col] = pd.to_numeric(df[close_col], errors='coerce')
    df[vol_col]   = pd.to_numeric(df[vol_col], errors='coerce')

    # Typical price and TP*V
    df["TypicalPrice"] = (df[high_col] + df[low_col] + df[close_col]) / 3.0
    df["TPxV"] = df["TypicalPrice"] * df[vol_col]

    # hourly VWAP (use lowercase 'h' to avoid future warning)
    hourly_vwap = df.groupby(pd.Grouper(freq="1h")).apply(
        lambda g: (g["TPxV"].sum() / g[vol_col].sum()) if g[vol_col].sum() != 0 else float("nan")
    )

    df["VWAP_1H"] = df.index.floor("h").map(hourly_vwap)

    # Save CSV robustly
    out_path = Path(OUT_CSV)
    try:
        saved_path = safe_save_csv(df, out_path)
        print("Saved CSV with VWAP to:", saved_path)
    except Exception as e:
        print("Failed to save CSV to preferred locations. Error:", e)
        raise

    # Prepare plotting dataframe
    plot_df = df[[close_col, "VWAP_1H"]].dropna(how="all")

    # crossovers detection
    s_close = plot_df[close_col]
    s_vwap = plot_df["VWAP_1H"]
    above = s_close > s_vwap
    cross_up = (~above.shift(1).fillna(False)) & (above.fillna(False))
    cross_down = (above.shift(1).fillna(False)) & (~above.fillna(False))

    # plot
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(plot_df.index, plot_df[close_col], label=f"Close ({close_col})", linewidth=1.0)
    ax.plot(plot_df.index, plot_df["VWAP_1H"], label="VWAP (hourly)", linewidth=1.5)

    ax.scatter(plot_df.index[cross_up], plot_df[close_col][cross_up], marker="^", s=80, zorder=5, label="Cross Above")
    ax.scatter(plot_df.index[cross_down], plot_df[close_col][cross_down], marker="v", s=80, zorder=5, label="Cross Below")

    ax.set_title("Close Price vs Hourly VWAP")
    ax.set_xlabel("Datetime")
    ax.set_ylabel("Price")
    ax.legend()
    ax.grid(True)
    plt.tight_layout()

    # save plot next to the script (overwrite permitted by default)
    try:
        plt.savefig(OUT_PLOT, dpi=150)
        print("Saved plot to:", Path(OUT_PLOT).absolute())
    except PermissionError:
        # fallback to temp dir
        alt_plot = Path(tempfile.gettempdir()) / (Path(OUT_PLOT).stem + "_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + Path(OUT_PLOT).suffix)
        plt.savefig(alt_plot, dpi=150)
        print("Plot save permission denied in folder; saved plot to:", alt_plot)
    plt.show()

if __name__ == "__main__":
    main()
