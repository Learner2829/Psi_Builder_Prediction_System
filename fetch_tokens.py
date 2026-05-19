import requests
import sqlite3
import os
import datetime

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "trades.db")
SCRIP_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# Indices to fetch
# --- AFTER ---
INDICES_TO_FETCH = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
# Stocks List
ALLOWED_STOCKS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "ITC", "LT", "AXISBANK", "KOTAKBANK",
    "SBIN", "BHARTIARTL", "BAJFINANCE", "ASIANPAINT", "MARUTI", "TITAN", "SUNPHARMA",
    "ULTRACEMCO", "TATAMOTORS", "TATASTEEL", "NTPC", "POWERGRID", "M&M", "INDUSINDBK",
    "HCLTECH", "ADANIENT", "ADANIPORTS", "COALINDIA", "ONGC", "BPCL", "BAJAJFINSV",
    "JSWSTEEL", "HINDALCO", "GRASIM", "DRREDDY", "CIPLA", "WIPRO", "TECHM", "SBILIFE",
    "HDFCLIFE", "APOLLOHOSP", "EICHERMOT", "DIVISLAB", "TATACONSUM", "BRITANNIA", "HEROMOTOCO"
]

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS scrips (
            token TEXT PRIMARY KEY, 
            symbol TEXT, 
            name TEXT, 
            expiry TEXT, 
            strike REAL, 
            type TEXT, 
            instrumenttype TEXT, 
            exch_seg TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_name_expiry ON scrips (name, expiry)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_symbol ON scrips (symbol)')
        conn.commit()

def update_master_db():
    print("⏳ Downloading Angel One Master JSON (This takes ~20s)...")
    
    try:
        r = requests.get(SCRIP_URL, timeout=60).json()
        print(f"✅ Downloaded {len(r)} items. Filtering & Normalizing...")
        
        data = []
        allowed_set = set(ALLOWED_STOCKS)
        counts = {i: 0 for i in INDICES_TO_FETCH}
        
        for i in r:
            raw_name = i.get('name')
            instrument = i.get('instrumenttype')
            symbol = i.get('symbol')
            exch = i.get('exch_seg')
            token = i.get('token')
            
            # --- NORMALIZATION LOGIC ---
            # Map "S&P BSE SENSEX" -> "SENSEX"
            name = raw_name
            if raw_name:
                if "BANKEX" in raw_name: name = "BANKEX"
                elif "SENSEX" in raw_name: name = "SENSEX"
                elif "NIFTY" in raw_name and "BANK" in raw_name: name = "BANKNIFTY"
                elif "FINNIFTY" in raw_name: name = "FINNIFTY"
                elif "MIDCPNIFTY" in raw_name: name = "MIDCPNIFTY"
                elif raw_name == "NIFTY": name = "NIFTY"

            # 1. INDICES (NSE & BSE)
            if name in INDICES_TO_FETCH:
                # Capture Options (NSE & BSE)
                # Note: BFO often uses 'BSEN' or 'IDXOPT' or 'IO'
                is_opt = (instrument in ['OPTIDX', 'BSEN', 'IDXOPT', 'IO'])
                is_bfo_segment = (exch == 'BFO' and (symbol.endswith('CE') or symbol.endswith('PE')))
                
                if is_opt or is_bfo_segment:
                    try:
                        s = float(i['strike'])
                        
                        # CRITICAL FIX: Scaling for BSE Strikes
                        # If strike > 100000, it's likely scaled by 100 (e.g. 7500000 -> 75000)
                        if s > 100000: s = s / 100
                            
                        expiry = i.get('expiry')
                        
                        # Determine CE/PE
                        if symbol.endswith('CE'): op_type = 'CE'
                        elif symbol.endswith('PE'): op_type = 'PE'
                        else: continue 
                        
                        data.append((token, symbol, name, expiry, s, op_type, instrument, exch))
                        counts[name] += 1
                    except: continue
            
            # 2. INDIA VIX
            elif raw_name == 'INDIA VIX':
                 data.append((token, symbol, 'INDIA VIX', '', 0, 'IDX', 'IDX', 'NSE'))

            # 3. STOCKS
            elif raw_name in allowed_set and instrument == '' and symbol.endswith('-EQ') and exch == 'NSE':
                 data.append((token, symbol, raw_name, '', 0, 'EQ', 'EQ', 'NSE'))

        if data:
            init_db()
            with get_db_connection() as conn:
                conn.execute("DELETE FROM scrips")
                conn.executemany('INSERT INTO scrips VALUES (?,?,?,?,?,?,?,?)', data)
                today = datetime.date.today().strftime("%Y-%m-%d")
                conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('last_updated', ?)", (today,))
                conn.commit()
            
            print(f"🎉 Success! DB Updated with {len(data)} Scrips.")
            print("📊 Breakdown:")
            for k, v in counts.items():
                print(f"   - {k}: {v} strikes found")
                
            if counts['BANKEX'] == 0:
                print("❌ ERROR: Still found 0 BANKEX tokens. Check if 'S&P BSE BANKEX' exists in source.")
        else:
            print("⚠️ Warning: No data found!")

    except Exception as e:
        print(f"❌ Error updating DB: {e}")

if __name__ == "__main__":
    update_master_db()