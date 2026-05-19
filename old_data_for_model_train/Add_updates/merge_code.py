import os
import pandas as pd
import numpy as np
from pathlib import Path
import datetime
import tempfile

# ---------- CONFIG ----------
INPUT_FOLDER = 'Stock_Data_Files'
OUTPUT_FOLDER = 'indicators_combined'

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ---------- SuperTrend ----------
ATR_PERIOD = 14
MULTIPLIER = 3.0

def calculate_supertrend(df):
    df['High-Low'] = df['high'] - df['low']
    df['High-Previous Close'] = abs(df['high'] - df['close'].shift(1))
    df['Low-Previous Close'] = abs(df['low'] - df['close'].shift(1))

    df['True Range'] = df[['High-Low', 'High-Previous Close', 'Low-Previous Close']].max(axis=1)
    df['ATR'] = df['True Range'].rolling(window=ATR_PERIOD).mean()

    df['Basic Upper Band'] = (df['high'] + df['low']) / 2 + MULTIPLIER * df['ATR']
    df['Basic Lower Band'] = (df['high'] + df['low']) / 2 - MULTIPLIER * df['ATR']

    df['SuperTrend'] = np.nan
    for i in range(1, len(df)):
        if df['close'][i] > (df['SuperTrend'][i-1] if not pd.isna(df['SuperTrend'][i-1]) else df['Basic Lower Band'][i]):
            df.loc[df.index[i], 'SuperTrend'] = df['Basic Lower Band'][i]
        else:
            df.loc[df.index[i], 'SuperTrend'] = df['Basic Upper Band'][i]

    df['SuperTrend'].fillna(method='ffill', inplace=True)
    return df

# ---------- MACD ----------
def calculate_macd(df):
    df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD Line'] = df['EMA12'] - df['EMA26']
    df['Signal Line'] = df['MACD Line'].ewm(span=9, adjust=False).mean()
    df['MACD Histogram'] = df['MACD Line'] - df['Signal Line']
    return df

# ---------- VWAP ----------
def calculate_vwap(df):
    df["TypicalPrice"] = (df["high"] + df["low"] + df["close"]) / 3.0
    df["TPxV"] = df["TypicalPrice"] * df["volume"]

    hourly_vwap = df.groupby(pd.Grouper(key="date", freq="1H")).apply(
        lambda g: (g["TPxV"].sum() / g["volume"].sum()) if g["volume"].sum() != 0 else float("nan")
    )
    df["VWAP_1H"] = df["date"].dt.floor("h").map(hourly_vwap)
    return df

# ---------- SAVE ----------
def safe_save_csv(df, preferred_path: Path):
    try:
        df.to_csv(preferred_path, index=False)
        return preferred_path
    except PermissionError:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_name = preferred_path.with_name(preferred_path.stem + "_" + ts + preferred_path.suffix)
        try:
            df.to_csv(fallback_name, index=False)
            return fallback_name
        except PermissionError:
            temp_dir = Path(tempfile.gettempdir())
            fallback_temp = temp_dir / fallback_name.name
            df.to_csv(fallback_temp, index=False)
            return fallback_temp

# ---------- PROCESS ----------
def process_file(file_path):
    df = pd.read_csv(file_path, parse_dates=['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Apply all indicators
    df = calculate_supertrend(df)
    df = calculate_macd(df)
    df = calculate_vwap(df)

    # Save final combined output
    output_file = Path(OUTPUT_FOLDER) / f"combined_{Path(file_path).name}"
    saved_path = safe_save_csv(df, output_file)
    print(f"Processed and saved: {saved_path}")

def main():
    for file_name in os.listdir(INPUT_FOLDER):
        if file_name.endswith('.csv'):
            process_file(os.path.join(INPUT_FOLDER, file_name))
    print("✅ All files processed successfully!")

if __name__ == "__main__":
    main()
