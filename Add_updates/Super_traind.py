import os
import pandas as pd
import numpy as np

# Define the input folder where your stock data files are stored
input_folder = 'Stock_Data_Files'

# Define the output folder where the processed files will be saved
output_folder = 'supert_traind_calculated'

# Create the output folder if it does not exist
os.makedirs(output_folder, exist_ok=True)

# Define parameters for SuperTrend calculation
ATR_PERIOD = 14  # ATR Period (in hours)
MULTIPLIER = 3.0  # Multiplier for SuperTrend

# Function to calculate SuperTrend for a single dataframe
def calculate_supertrend(df):
    # Calculate the True Range (TR)
    df['High-Low'] = df['high'] - df['low']
    df['High-Previous Close'] = abs(df['high'] - df['close'].shift(1))
    df['Low-Previous Close'] = abs(df['low'] - df['close'].shift(1))

    df['True Range'] = df[['High-Low', 'High-Previous Close', 'Low-Previous Close']].max(axis=1)

    # Calculate the ATR (Average True Range)
    df['ATR'] = df['True Range'].rolling(window=ATR_PERIOD).mean()

    # Calculate the Basic Upper and Lower Bands
    df['Basic Upper Band'] = (df['high'] + df['low']) / 2 + MULTIPLIER * df['ATR']
    df['Basic Lower Band'] = (df['high'] + df['low']) / 2 - MULTIPLIER * df['ATR']

    # Initialize SuperTrend columns
    df['SuperTrend'] = np.nan

    # Calculate the SuperTrend
    for i in range(1, len(df)):
        if df['close'][i] > df['SuperTrend'][i-1]:
            df['SuperTrend'][i] = df['Basic Lower Band'][i]
        else:
            df['SuperTrend'][i] = df['Basic Upper Band'][i]

    # Fill any missing values in the SuperTrend column by using forward fill
    df['SuperTrend'].fillna(method='ffill', inplace=True)

    return df

# Loop through each file in the input folder, process it, and save the result
for file_name in os.listdir(input_folder):
    file_path = os.path.join(input_folder, file_name)

    # Check if the file is a CSV file
    if file_name.endswith('.csv'):
        # Load the CSV file into a DataFrame
        df = pd.read_csv(file_path, parse_dates=['date'])

        # Calculate SuperTrend for the current stock data
        df_with_supertrend = calculate_supertrend(df)

        # Define the output file path
        output_file = os.path.join(output_folder, f"supert_traind_{file_name}")

        # Save the updated dataframe with the SuperTrend column back to the output folder
        df_with_supertrend.to_csv(output_file, index=False)

        print(f"SuperTrend added to {file_name} and saved as {output_file}")

print("All files processed successfully!")
