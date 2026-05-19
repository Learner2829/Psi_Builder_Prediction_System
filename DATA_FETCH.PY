from SmartApi import SmartConnect
import pyotp
import pandas as pd
from datetime import datetime, timedelta
import time

# ==========================================
# CREDENTIALS CONFIGURATION
# ==========================================
API_KEY = "K7WY6yi9"
CLIENT_CODE = "A56068389"
PIN = "1207"
TOTP_SECRET = "6FTC7CSOZVK7F7AUT7CVWWSSWQ"  # The QR Code string provided by Angel One

# Initialize SmartConnect
smartApi = SmartConnect(API_KEY)

def login():
    try:
        # Generate TOTP
        totp = pyotp.TOTP(TOTP_SECRET).now()
        
        # Generate Session
        data = smartApi.generateSession(CLIENT_CODE, PIN, totp)
        if data['status']:
            print("Login Successful!")
            return True
        else:
            print(f"Login Failed: {data}")
            return False
    except Exception as e:
        print(f"Error during login: {e}")
        return False

# ==========================================
# INDEX TOKENS DICTIONARY
# ==========================================
# Note: Angel One recently updated index tokens (often prefixed with 999)
# You can always verify the latest tokens in the OpenAPIScripMaster.json
indices_data = {
    "NIFTY": {"exchange": "NSE", "token": "99926000"},
    "BANKNIFTY": {"exchange": "NSE", "token": "99926009"},
    "FINNIFTY": {"exchange": "NSE", "token": "99926037"},
    "MIDCPNIFTY": {"exchange": "NSE", "token": "99926074"},
    "SENSEX": {"exchange": "BSE", "token": "99919000"},
    "INDIAVIX": {"exchange": "NSE", "token": "99926017"}
}

def fetch_5_days_ohlc():
    # Calculate Date Range (Last 5 Days)
    # Smart API requires "YYYY-MM-DD HH:MM" format
    end_date = datetime.now()
    start_date = end_date - timedelta(days=5)
    
    from_date_str = start_date.strftime("%Y-%m-%d 09:15")
    to_date_str = end_date.strftime("%Y-%m-%d 15:30")
    
    print(f"Fetching data from {from_date_str} to {to_date_str}...\n")
    
    all_dataframes = {}

    for index_name, info in indices_data.items():
        try:
            historicParam = {
                "exchange": info["exchange"],
                "symboltoken": info["token"],
                "interval": "FIVE_MINUTE",
                "fromdate": from_date_str,
                "todate": to_date_str
            }
            
            # Fetch Candle Data
            response = smartApi.getCandleData(historicParam)
            
            if response['status'] and response['data']:
                # The response data format: [timestamp, open, high, low, close, volume]
                columns = ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
                df = pd.DataFrame(response['data'], columns=columns)
                
                # Convert string timestamp to datetime object
                df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                all_dataframes[index_name] = df
                
                print(f"Successfully fetched {len(df)} records for {index_name}")
            else:
                print(f"Failed to fetch or no data available for {index_name}: {response.get('message')}")
                
        except Exception as e:
            print(f"API Request failed for {index_name}: {e}")
            
        # Add a slight delay to respect API rate limits
        time.sleep(0.5)
        
    return all_dataframes

if __name__ == "__main__":
    if login():
        fetched_data = fetch_5_days_ohlc()
        
        # Example of how to view the fetched data
        if "NIFTY" in fetched_data:
            print("\n--- NIFTY 50 (Last 5 rows) ---")
            print(fetched_data["NIFTY"].tail())
            
        # Logout securely after tasks are complete
        smartApi.terminateSession(CLIENT_CODE)
        print("\nLogged out successfully.")