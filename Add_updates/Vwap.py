import pandas as pd
import os
import sys
import datetime
from pathlib import Path
import tempfile

# ---------- CONFIG ----------
# Folder paths
INPUT_FOLDER = 'Stock_Data_Files'    # folder with the CSV files
OUTPUT_FOLDER = 'vwap_calculated'          # output folder for processed files

# Create the output folder if it doesn't exist
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

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

def process_file(file_path):
    df = pd.read_csv(file_path, low_memory=False)
    print(f"Processing file: {file_path}")

    # Detect datetime column
    dt_col = find_column(df.columns, ["date", "datetime", "time", "timestamp"]) or df.columns[0]
    df[dt_col] = pd.to_datetime(df[dt_col], errors='coerce')
    if df[dt_col].isna().all():
        raise ValueError(f"Could not parse any datetime values from column: {dt_col}")

    df = df.sort_values(dt_col).set_index(dt_col)

    # Detect price/volume columns
    high_col = find_column(df.columns, ["high", "h"])
    low_col = find_column(df.columns, ["low", "l"])
    close_col = find_column(df.columns, ["close", "c", "last", "price"])
    vol_col = find_column(df.columns, ["volume", "vol", "v"])

    if not (high_col and low_col and close_col and vol_col):
        raise ValueError(f"Could not find required columns. Detected - high: {high_col}, low: {low_col}, close: {close_col}, volume: {vol_col}.\nColumns present: {', '.join(df.columns)}")

    # Convert to numeric
    df[high_col]  = pd.to_numeric(df[high_col], errors='coerce')
    df[low_col]   = pd.to_numeric(df[low_col], errors='coerce')
    df[close_col] = pd.to_numeric(df[close_col], errors='coerce')
    df[vol_col]   = pd.to_numeric(df[vol_col], errors='coerce')

    # Calculate Typical Price and TP*V
    df["TypicalPrice"] = (df[high_col] + df[low_col] + df[close_col]) / 3.0
    df["TPxV"] = df["TypicalPrice"] * df[vol_col]

    # VWAP Calculation: hourly VWAP
    hourly_vwap = df.groupby(pd.Grouper(freq="1h")).apply(
        lambda g: (g["TPxV"].sum() / g[vol_col].sum()) if g[vol_col].sum() != 0 else float("nan")
    )

    df["VWAP_1H"] = df.index.floor("h").map(hourly_vwap)

    # Save the CSV file with VWAP calculations (robust save)
    output_file = Path(OUTPUT_FOLDER) / f"vwap_{Path(file_path).name}"
    try:
        saved_path = safe_save_csv(df, output_file)
        print(f"Saved CSV with VWAP to: {saved_path}")
    except Exception as e:
        print(f"Failed to save CSV to preferred locations for {file_path}. Error: {e}")

def main():
    # Loop through all files in the input folder
    for file_name in os.listdir(INPUT_FOLDER):
        file_path = os.path.join(INPUT_FOLDER, file_name)

        # Process only CSV files
        if file_name.endswith('.csv'):
            process_file(file_path)

    print("All files processed successfully!")

if __name__ == "__main__":
    main()
