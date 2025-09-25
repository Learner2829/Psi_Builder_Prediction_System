import os
import pandas as pd

# Define the input folder where your stock data files are stored
input_folder = 'Stock_Data_Files'

# Define the output folder where the processed files will be saved
output_folder = 'macd_calculated'

# Create the output folder if it does not exist
os.makedirs(output_folder, exist_ok=True)

# Function to calculate MACD for a single dataframe
def calculate_macd(df):
    # Calculate the MACD Line (12-period EMA - 26-period EMA)
    df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD Line'] = df['EMA12'] - df['EMA26']

    # Calculate the Signal Line (9-period EMA of MACD Line)
    df['Signal Line'] = df['MACD Line'].ewm(span=9, adjust=False).mean()

    # Calculate the MACD Histogram (MACD Line - Signal Line)
    df['MACD Histogram'] = df['MACD Line'] - df['Signal Line']

    return df

# Loop through each file in the input folder, process it, and save the result
for file_name in os.listdir(input_folder):
    file_path = os.path.join(input_folder, file_name)

    # Check if the file is a CSV file
    if file_name.endswith('.csv'):
        # Load the CSV file into a DataFrame
        df = pd.read_csv(file_path, parse_dates=['date'])

        # Calculate MACD for the current stock data
        df_with_macd = calculate_macd(df)

        # Define the output file path
        output_file = os.path.join(output_folder, f"macd_{file_name}")

        # Save the updated dataframe with the MACD columns back to the output folder
        df_with_macd.to_csv(output_file, index=False)

        print(f"MACD added to {file_name} and saved as {output_file}")

print("All files processed successfully!")
