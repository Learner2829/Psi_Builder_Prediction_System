import threading, requests, pyotp, time, sqlite3, os, random, datetime, uuid, sys, json, re
import psutil
import numpy as np
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from scipy.stats import norm
from flask import Flask, jsonify, request, render_template, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from collections import defaultdict
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import fetch_tokens 
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# ==========================================
# --- CONFIGURATION (SECURED) ---
# ==========================================
API_KEY = os.getenv("API_KEY")
CLIENT_CODE = os.getenv("CLIENT_CODE")
PIN = os.getenv("PIN")
TOTP_KEY = os.getenv("TOTP_KEY")
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", 20000))

# FIXED: Replaced os.urandom(24) with a static string so the server doesn't 
# invalidate sessions (log you out) every time it restarts in development.
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret-key-change-in-production")

# Email Configuration for OTP
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# EXCHANGE TYPES: 1=NSE, 2=NFO, 3=BSE, 7=BFO
INDICES = {
    "NIFTY":      {"token": "99926000", "lot": 65, "spot_exch": 1, "symbol": "NIFTY"},
    "BANKNIFTY":  {"token": "99926009", "lot": 30, "spot_exch": 1, "symbol": "BANKNIFTY"},
    "FINNIFTY":   {"token": "99926037", "lot": 40, "spot_exch": 1, "symbol": "FINNIFTY"},
    "MIDCPNIFTY": {"token": "99926074", "lot": 75, "spot_exch": 1, "symbol": "MIDCPNIFTY"},
    "SENSEX":     {"token": "99919000", "lot": 10, "spot_exch": 3, "symbol": "SENSEX"},
    "INDIAVIX":   {"token": "99926017", "lot": 0,  "spot_exch": 1, "symbol": "INDIA VIX"}
}

# Stocks that are components of each option-chain index
# (matched against the `name` column in the scrips table)
INDEX_STOCKS = {
    "NIFTY50": [
        "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK",
        "BAJAJ-AUTO","BAJFINANCE","BAJAJFINSV","BEL","BPCL",
        "BHARTIARTL","BRITANNIA","CIPLA","COALINDIA","DIVISLAB",
        "DRREDDY","EICHERMOT","GRASIM","HCLTECH","HDFCBANK",
        "HDFCLIFE","HEROMOTOCO","HINDALCO","HINDUNILVR","ICICIBANK",
        "INDUSINDBK","INFY","ITC","JSWSTEEL","KOTAKBANK",
        "LT","M&M","MARUTI","NESTLEIND","NTPC","ONGC",
        "POWERGRID","RELIANCE","SBILIFE","SBIN","SHRIRAMFIN",
        "SUNPHARMA","TATACONSUM","TATAMOTORS","TATASTEEL",
        "TCS","TECHM","TITAN","ULTRACEMCO","WIPRO"
    ],
    "BANKNIFTY": [
        "AXISBANK","AUBANK","BANDHANBNK","BANKBARODA","FEDERALBNK",
        "HDFCBANK","ICICIBANK","IDFCFIRSTB","INDUSINDBK",
        "KOTAKBANK","PNB","SBIN"
    ],
    "FINNIFTY": [
        "ABCAPITAL","AUBANK","BAJFINANCE","BAJAJFINSV","CHOLAFIN",
        "HDFCAMC","HDFCBANK","HDFCLIFE","ICICIGI","ICICIPRULI",
        "ICICIBANK","KOTAKBANK","LICOF","MFSL","MOTILALOFS",
        "PFC","RECLTD","SBILIFE","SBIN","SHRIRAMFIN"
    ],
    "MIDCPNIFTY": [
        "ABCAPITAL","BALKRISIND","BANKINDIA","CANBK","CONCOR",
        "COROMANDEL","CUMMINSIND","DIXON","GLENMARK","GMRINFRA",
        "HINDPETRO","KPITTECH","LAURUSLABS","LICHSGFIN","LUPIN",
        "MGL","MPHASIS","OFSS","PERSISTENT","PIIND",
        "PRESTIGE","RBLBANK","SAIL","STAR","TATAELXSI"
    ],
    "SENSEX": [
        "ADANIENT","ADANIPORTS","ASIANPAINT","AXISBANK","BAJAJ-AUTO",
        "BAJFINANCE","BAJAJFINSV","BHARTIARTL","COALINDIA","DRREDDY",
        "HCLTECH","HDFCBANK","HINDUNILVR","ICICIBANK","INDUSINDBK",
        "INFY","ITC","JSWSTEEL","KOTAKBANK","LT",
        "M&M","MARUTI","NESTLEIND","NTPC","POWERGRID",
        "RELIANCE","SBIN","SUNPHARMA","TATAMOTORS","TCS",
        "TECHM","TITAN","ULTRACEMCO","WIPRO"
    ]
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "trades.db")

LIVE_FEED = {}
PCR_HISTORY = {idx: [] for idx in ["NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","SENSEX"]}
SUBSCRIBED_TOKENS = set()
sws = None
smartApi = None 

REQUEST_TOTAL = 0
REQUEST_LAST_CHECK = 0

# ====================================================
# BROKERAGE CALCULATOR ENGINE
# ====================================================
class BrokerageCalculator:
    def __init__(self):
        self.rates = {
            "equity_intraday": {
                "brokerage_pct": 0.0003, "brokerage_cap": 20, 
                "stt": 0.00025, "txn": 0.0000297, "stamp": 0.00003
            },
            "options": {
                "brokerage_flat": 20, 
                "stt": 0.000625,  
                "txn": 0.0005,    
                "stamp": 0.00003  
            }
        }
        self.sebi_rate = 0.000001 
        self.gst_rate = 0.18      

    def is_option(self, symbol):
        return bool(re.search(r'\d', symbol) or symbol.endswith('CE') or symbol.endswith('PE'))

    def calculate(self, symbol, buy_price, sell_price, qty):
        if buy_price == 0 or sell_price == 0: return 0.0

        is_opt = self.is_option(symbol)
        buy_val = buy_price * qty
        sell_val = sell_price * qty
        turnover = buy_val + sell_val

        brokerage, stt, txn_charge, stamp_duty = 0, 0, 0, 0
        
        if is_opt:
            r = self.rates["options"]
            brokerage = 40.0 
            stt = sell_val * r["stt"]
            txn_charge = turnover * r["txn"]
            stamp_duty = buy_val * r["stamp"]
        else:
            r = self.rates["equity_intraday"]
            b_buy = min(buy_val * r["brokerage_pct"], r["brokerage_cap"])
            b_sell = min(sell_val * r["brokerage_pct"], r["brokerage_cap"])
            brokerage = b_buy + b_sell
            stt = sell_val * r["stt"]
            txn_charge = turnover * r["txn"]
            stamp_duty = buy_val * r["stamp"]

        sebi_charge = turnover * self.sebi_rate
        gst = (brokerage + txn_charge + sebi_charge) * self.gst_rate
        
        total = brokerage + stt + txn_charge + sebi_charge + stamp_duty + gst
        return round(total, 2)

broker_engine = BrokerageCalculator()

# ====================================================
# 1. DATABASE & EMAIL LAYER
# ====================================================
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        
        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            last_name TEXT,
            age INTEGER,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT
        )''')
        
        # Trades table with user_id
        c.execute('''CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY, user_id INTEGER, time TEXT, symbol TEXT, token TEXT, type TEXT, qty INTEGER, 
            entry_price REAL, exit_price REAL, status TEXT, sl REAL, target REAL, 
            exit_reason TEXT, charges REAL DEFAULT 0.0, gross_pnl REAL DEFAULT 0.0
        )''')

        # Add user_id column if migrating from old DB
        try:
            c.execute("ALTER TABLE trades ADD COLUMN user_id INTEGER")
        except:
            pass # Column already exists
            
        # Price prediction history table
        c.execute('''CREATE TABLE IF NOT EXISTS historical_data (
            symbol TEXT, timestamp TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            UNIQUE(symbol, timestamp)
        )''')
        
        # PCR History table
        c.execute('''CREATE TABLE IF NOT EXISTS pcr_logs (
            index_name TEXT, date TEXT, time TEXT, pcr REAL, ce_oi INTEGER, pe_oi INTEGER,
            UNIQUE(index_name, date, time)
        )''')
        conn.commit()

def db_query(query, args=(), one=False):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(query, args)
            rv = cur.fetchall()
            return (rv[0] if rv else None) if one else rv
    except Exception as e: 
        print(f"DB Query Error: {e}")
        return []

def db_execute(query, args=()):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.cursor().execute(query, args)
            conn.commit()
    except Exception as e: print(f"DB Execute Error: {e}")

def send_email(to_email, subject, body):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("❌ Email credentials missing in .env")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = f"Algo Trade <{EMAIL_SENDER}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False

# ====================================================
# --- AUTHENTICATION & APP FLOW ROUTES ---
# ====================================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def count_api_hit():
    global REQUEST_TOTAL
    REQUEST_TOTAL += 1

def monitor_traffic():
    global REQUEST_TOTAL, REQUEST_LAST_CHECK
    while True:
        time.sleep(3)
        diff = REQUEST_TOTAL - REQUEST_LAST_CHECK
        rps = diff / 3.0
        cpu = psutil.cpu_percent()
        sub_count = len(LIVE_FEED)
        GREEN, CYAN, YELLOW, RESET = '\033[92m', '\033[96m', '\033[93m', '\033[0m'
        print(f"{CYAN}[STATS]{RESET} ⚡ API: {GREEN}{rps:.1f} req/s{RESET} | 📡 Subs: {YELLOW}{sub_count}{RESET} | 🖥️ CPU: {cpu}%")
        REQUEST_LAST_CHECK = REQUEST_TOTAL

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    action = request.args.get('action')
    show_signup = True if action == 'signup' else False
    
    if request.args.get('abort_signup'):
        session.pop('signup_data', None)
        return redirect(url_for('login', action='signup'))

    if request.method == 'POST':
        # 1. HANDLE LOGIN
        if 'login' in request.form:
            username = request.form.get('username')
            password = request.form.get('password')
            user = db_query("SELECT * FROM users WHERE username = ?", (username,), one=True)
            
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                return redirect(url_for('dashboard'))
            return render_template('login.html', error="Invalid username or password", show_signup=False)

        # 2. HANDLE INITIAL SIGNUP
        elif 'signup' in request.form:
            data = request.form
            existing = db_query("SELECT * FROM users WHERE username = ? OR email = ?", (data['username'], data['email']), one=True)
            if existing:
                return render_template('login.html', error="Username or email already exists.", show_signup=True)
            
            otp = str(random.randint(100000, 999999))
            
            session['signup_data'] = {
                'first_name': data['first_name'], 'last_name': data['last_name'],
                'age': data['age'], 'username': data['username'],
                'email': data['email'], 'password': generate_password_hash(data['password']),
                'otp': otp
            }
            
            email_body = f"<h3>Your Verification Code</h3><p>Use this code to verify your Algo Trade account: <h2>{otp}</h2></p>"
            send_email(data['email'], "Verify your Algo Trade Account", email_body)
            
            return render_template('login.html', show_signup=True, show_otp_modal=True)

        # 3. HANDLE OTP VERIFICATION
        elif 'verify_otp' in request.form:
            entered_otp = request.form.get('otp_code')
            signup_data = session.get('signup_data')
            
            if not signup_data:
                return render_template('login.html', error="Session expired. Please sign up again.", show_signup=True)
                
            if entered_otp == signup_data['otp']:
                db_execute("INSERT INTO users (first_name, last_name, age, username, email, password, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (signup_data['first_name'], signup_data['last_name'], signup_data['age'], 
                           signup_data['username'], signup_data['email'], signup_data['password'], 
                           datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                
                welcome_body = f"<h3>Welcome to Algo Trade, {signup_data['first_name']}!</h3><p>Your account is setup and ready for paper trading.</p>"
                send_email(signup_data['email'], "Welcome to Algo Trade!", welcome_body)
                
                session.pop('signup_data', None)
                return render_template('login.html', success="Account verified! Please sign in.", show_signup=False)
            else:
                return render_template('login.html', error="Invalid OTP code.", show_signup=True, show_otp_modal=True)

        # 4. RESEND OTP
        elif 'resend_otp' in request.form:
            signup_data = session.get('signup_data')
            if signup_data:
                new_otp = str(random.randint(100000, 999999))
                signup_data['otp'] = new_otp
                session['signup_data'] = signup_data
                email_body = f"<h3>Your New Verification Code</h3><p>Code: <h2>{new_otp}</h2></p>"
                send_email(signup_data['email'], "New OTP - Algo Trade", email_body)
                return render_template('login.html', success="A new code has been sent.", show_signup=True, show_otp_modal=True)

    return render_template('login.html', show_signup=show_signup)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard(): return render_template('dashboard.html')

@app.route('/trade')
@login_required
def chain(): return render_template('chain.html')

@app.route('/search')
@login_required
def search_page(): return render_template('search.html')

@app.route('/prediction')
@login_required
def prediction_page(): 
    return render_template('prediction.html')


# ====================================================
# 2. ISOLATED PORTFOLIO & PREDICTION ENGINE
# ====================================================
def get_live_price_safe(token):
    if token in LIVE_FEED: return LIVE_FEED[token]['ltp']
    return 0

def fetch_historical_candles(symbol, token, spot_exch_code):
    global smartApi
    if not smartApi: 
        return []
    
    exchange = "NSE" if spot_exch_code == 1 else "BSE"
    to_date = datetime.datetime.now()
    from_date = to_date - datetime.timedelta(days=2)
    
    payload = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": "FIVE_MINUTE",
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M")
    }
    
    try:
        response = smartApi.getCandleData(payload)
        if response and response.get('status') and response.get('data'):
            return response['data']
    except Exception as e:
        print(f"Historical Data Fetch Error for {symbol}: {e}")
    
    return []

def predict_next_price_lr(candles):
    if not candles or len(candles) < 2:
        return None, None
    
    closes = [candle[4] for candle in candles]
    x = np.arange(len(closes))
    y = np.array(closes)
    
    m, c = np.polyfit(x, y, 1)
    
    next_x = len(closes)
    predicted_price = m * next_x + c
    trend = "BULLISH" if m > 0 else "BEARISH"
    
    return round(predicted_price, 2), trend

def calculate_portfolio(user_id):
    cash = INITIAL_CAPITAL
    invested, curr_val = 0, 0
    trades_list = [] 
    
    rows = db_query("SELECT * FROM trades WHERE user_id = ? ORDER BY time DESC", (user_id,))
    
    for row in rows:
        t = dict(row)
        qty, entry, tr_type = t['qty'], t['entry_price'], t['type']
        
        if t['status'] == 'CLOSED':
            exit_p = t['exit_price']
            t['current_price'] = exit_p
            charges = t.get('charges', 0.0) 
            if not charges: 
                charges = broker_engine.calculate(t['symbol'], entry, exit_p, qty)
        else:
            ltp = get_live_price_safe(t['token'])
            if ltp == 0: ltp = entry 
            t['current_price'] = round(ltp, 2)
            exit_p = ltp
            charges = broker_engine.calculate(t['symbol'], entry, ltp, qty)

        if tr_type == 'BUY': gross_pnl = (exit_p - entry) * qty
        else: gross_pnl = (entry - exit_p) * qty
            
        net_pnl = gross_pnl - charges
        t['gross_pnl'] = round(gross_pnl, 2)
        t['charges'] = round(charges, 2)
        t['pnl'] = round(net_pnl, 2)

        trades_list.append(t) 

        if t['status'] == 'CLOSED':
            cash += net_pnl
        else:
            if tr_type == 'BUY':
                cost = entry * qty
                cash -= cost
                curr_val += (exit_p * qty)
                invested += cost 
            else:
                margin_req = qty * 2000 
                cash -= margin_req
                invested += margin_req
            
    total_net_pnl = sum(x['pnl'] for x in trades_list)
    net_worth = INITIAL_CAPITAL + total_net_pnl
    free_cash = net_worth - invested

    return {
        'metrics': {
            'cash': round(free_cash, 2), 
            'invested': round(invested, 2), 
            'net_worth': round(net_worth, 2), 
            'pnl': round(total_net_pnl, 2)
        }, 
        'positions': trades_list
    }

def monitor_positions():
    while True:
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM trades WHERE status = 'OPEN'")
                open_trades = cur.fetchall()
                
                for row in open_trades:
                    t = dict(row)
                    ltp = get_live_price_safe(t['token'])
                    if ltp == 0: continue
                    
                    sl, target, tr_type = t['sl'], t['target'], t['type']
                    exit_reason = None
                    
                    if tr_type == 'BUY':
                        if sl > 0 and ltp <= sl: exit_reason = "HIT SL"
                        if target > 0 and ltp >= target: exit_reason = "HIT TARGET"
                    else: 
                        if sl > 0 and ltp >= sl: exit_reason = "HIT SL"
                        if target > 0 and ltp <= target: exit_reason = "HIT TARGET"
                    
                    if exit_reason:
                        charges = broker_engine.calculate(t['symbol'], t['entry_price'], ltp, t['qty'])
                        cur.execute("UPDATE trades SET status=?, exit_price=?, exit_reason=?, charges=? WHERE id=?", 
                                   ('CLOSED', round(ltp, 2), exit_reason, charges, t['id']))
                        conn.commit()
        except Exception as e: 
            print(f"Monitor Error: {e}")
        time.sleep(0.5)

# ====================================================
# 3. API ROUTES
# ====================================================

@app.route('/api/predict_indices', methods=['GET'])
@login_required
def run_predictions():
    results = []
    
    for name, details in INDICES.items():
        if name == "INDIAVIX": continue 
        
        token = details["token"]
        spot_exch = details["spot_exch"]
        
        candles = fetch_historical_candles(name, token, spot_exch)
        
        if candles:
            # Store data in background
            for c in candles:
                db_execute(
                    "INSERT OR IGNORE INTO historical_data (symbol, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, c[0], c[1], c[2], c[3], c[4], c[5])
                )
            
            predicted_price, trend = predict_next_price_lr(candles)
            current_price = candles[-1][4]
            diff = round(predicted_price - current_price, 2)
            
            results.append({
                "symbol": name,
                "current_price": current_price,
                "predicted_price": predicted_price,
                "difference": diff,
                "trend": trend,
                "data_points": len(candles)
            })
            
    return jsonify({"status": "success", "predictions": results})

@app.route('/api/portfolio')
@login_required
def portfolio():
    data = calculate_portfolio(session['user_id'])
    active_tokens = [t['token'] for t in data['positions'] if t['status'] == 'OPEN']
    return jsonify({'positions': data['positions'], 'metrics': data['metrics'], 'tokens': active_tokens})

@app.route('/api/orders/place', methods=['POST'])
@login_required
def place_order():
    d = request.json
    data = calculate_portfolio(session['user_id'])
    token, tr_type = d.get('token'), d.get('type', 'BUY')
    if token not in LIVE_FEED or LIVE_FEED[token]['ltp'] == 0: return jsonify({'status': 'error', 'msg': 'Price not loaded. Please wait.'})
    price = LIVE_FEED[token]['ltp']
    qty = int(d.get('qty', 0))
    if qty == 0: return jsonify({'status': 'error', 'msg': 'Qty cannot be 0'})
    avail_cash = data['metrics']['cash'] 
    required_margin = price * qty if tr_type == 'BUY' else qty * 2000 
    if required_margin > avail_cash: return jsonify({'status': 'error', 'msg': f'Insufficient Margin! Req: {required_margin/1000:.1f}k'})
    
    db_execute('''INSERT INTO trades (id, user_id, time, symbol, token, type, qty, entry_price, exit_price, status, sl, target, exit_reason, charges, gross_pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
              (str(uuid.uuid4())[:8], session['user_id'], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), d.get('symbol'), token, tr_type, qty, round(price, 2), 0.0, 'OPEN', float(d.get('sl') or 0), float(d.get('target') or 0), 'MANUAL', 0.0, 0.0))
    return jsonify({'status': 'ok'})

@app.route('/api/orders/modify', methods=['POST'])
@login_required
def modify_order():
    d = request.json
    try:
        trade = db_query("SELECT status FROM trades WHERE id=? AND user_id=?", (d.get('id'), session['user_id']), one=True)
        if trade and trade['status'] == 'OPEN':
            db_execute("UPDATE trades SET sl=?, target=? WHERE id=?", (float(d.get('sl') or 0), float(d.get('target') or 0), d.get('id')))
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'msg': 'Trade closed or unauthorized'})
    except: return jsonify({'status': 'error', 'msg': 'Error'})

@app.route('/api/orders/exit', methods=['POST'])
@login_required
def exit_order():
    tid = request.json.get('id')
    trade = db_query("SELECT * FROM trades WHERE id = ? AND user_id = ?", (tid, session['user_id']), one=True)
    if trade and trade['status'] == 'OPEN':
        ltp = get_live_price_safe(trade['token'])
        charges = broker_engine.calculate(trade['symbol'], trade['entry_price'], ltp, trade['qty'])
        db_execute("UPDATE trades SET status=?, exit_price=?, exit_reason=?, charges=? WHERE id=?", 
                  ('CLOSED', round(ltp, 2), 'MANUAL', charges, tid))
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error', 'msg': 'Failed or unauthorized'})

@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    raw_tokens = request.json.get('tokens', [])
    new_tokens = []
    for t in raw_tokens:
        if t not in SUBSCRIBED_TOKENS:
            new_tokens.append(t)
            SUBSCRIBED_TOKENS.add(t)
        if t not in LIVE_FEED: LIVE_FEED[t] = {'ltp': 0, 'close': 0, 'pct': "0.00%", 'vol': 0, 'atp': 0, 'oi': 0}

    if sws and new_tokens:
        nse_cm, nse_fo, bse_cm, bse_fo = [], [], [], []
        spot_map = {v['token']: v for v in INDICES.values()}
        
        unknown = [t for t in new_tokens if t not in spot_map]
        token_info = {}
        if unknown:
            rows = db_query(f"SELECT token, exch_seg FROM scrips WHERE token IN ({','.join('?'*len(unknown))})", unknown)
            for r in rows: token_info[r['token']] = r['exch_seg'] 
            
        for t in new_tokens:
            if t in spot_map:
                ex = spot_map[t]['spot_exch']
                if ex == 1: nse_cm.append(t)
                elif ex == 3: bse_cm.append(t)
            else:
                seg = token_info.get(t, 'NFO') 
                if seg == 'NSE': nse_cm.append(t)
                elif seg == 'BSE': bse_cm.append(t)
                elif seg == 'BFO': bse_fo.append(t)
                else: nse_fo.append(t)
        
        if nse_cm: sws.subscribe("snapquote", 3, [{"exchangeType": 1, "tokens": nse_cm}])
        if nse_fo: sws.subscribe("snapquote", 3, [{"exchangeType": 2, "tokens": nse_fo}])
        if bse_cm: sws.subscribe("snapquote", 3, [{"exchangeType": 3, "tokens": bse_cm}])
        if bse_fo: sws.subscribe("snapquote", 3, [{"exchangeType": 4, "tokens": bse_fo}])

    return jsonify({'status': 'ok', 'new_subs': len(new_tokens)})

@app.route('/api/market_data')
def market(): return jsonify(LIVE_FEED)

@app.route('/api/search', methods=['GET'])
@login_required
def search_api():
    query = request.args.get('q', '').upper().strip()
    index = request.args.get('index', '').upper().strip()   # e.g. NIFTY50, BANKNIFTY …
    if not query or len(query) < 1: return jsonify([])

    if index and index in INDEX_STOCKS:
        # Search only within the requested index's component stocks
        stocks = INDEX_STOCKS[index]
        phs = ','.join('?' * len(stocks))
        rows = db_query(
            f"SELECT token, symbol, name FROM scrips WHERE type='EQ' AND symbol LIKE ? AND name IN ({phs}) LIMIT 30",
            (query + '%',) + tuple(stocks)
        )
    else:
        # Search all F&O-eligible equities (have a futures contract in the DB)
        rows = db_query(
            "SELECT token, symbol, name FROM scrips WHERE type='EQ' AND symbol LIKE ? "
            "AND name IN (SELECT DISTINCT name FROM scrips WHERE type='FUTSTK') LIMIT 30",
            (query + '%',)
        )
    return jsonify([{'token': r['token'], 'symbol': r['symbol'], 'name': r['name']} for r in rows])


@app.route('/api/index_stocks', methods=['GET'])
@login_required
def index_stocks_api():
    """Return ALL component stocks for a given index with their NSE-EQ tokens."""
    index = request.args.get('index', '').upper().strip()
    if not index or index not in INDEX_STOCKS:
        return jsonify({'error': 'Unknown index'}), 400

    stocks = INDEX_STOCKS[index]
    phs = ','.join('?' * len(stocks))
    rows = db_query(
        f"SELECT token, symbol, name FROM scrips WHERE type='EQ' AND name IN ({phs}) ORDER BY name",
        tuple(stocks)
    )
    # Build index membership map for badge display
    membership = {}
    for idx_key, members in INDEX_STOCKS.items():
        for m in members:
            membership.setdefault(m, []).append(idx_key)

    result = []
    for r in rows:
        badges = membership.get(r['name'], [])
        result.append({
            'token': r['token'],
            'symbol': r['symbol'],
            'name': r['name'],
            'indices': badges
        })
    return jsonify(result)


# ── PCR SNAPSHOT & HISTORY ──────────────────────────────────────────────────
def snapshot_pcr():
    """Calculate and store current PCR for each index using live OI from LIVE_FEED."""
    now = datetime.datetime.now()
    t_str = now.strftime("%H:%M")
    date_str = now.strftime("%Y-%m-%d")
    
    for idx in PCR_HISTORY.keys():
        # Get the nearest (front-week) expiry for this index
        row = db_query("SELECT MIN(expiry) as exp FROM scrips WHERE name=? AND type IN ('CE','PE')", (idx,), one=True)
        if not row or not row['exp']:
            continue
        expiry = row['exp']
        # Get all CE and PE tokens for this index+expiry
        ce_rows = db_query("SELECT token FROM scrips WHERE name=? AND expiry=? AND type='CE'", (idx, expiry))
        pe_rows = db_query("SELECT token FROM scrips WHERE name=? AND expiry=? AND type='PE'", (idx, expiry))
        ce_oi = sum(LIVE_FEED.get(r['token'], {}).get('oi', 0) for r in ce_rows)
        pe_oi = sum(LIVE_FEED.get(r['token'], {}).get('oi', 0) for r in pe_rows)
        
        if ce_oi == 0 and pe_oi == 0: continue # Skip if no data
        pcr = round(pe_oi / ce_oi, 3) if ce_oi > 0 else 0
        
        db_execute("INSERT OR REPLACE INTO pcr_logs (index_name, date, time, pcr, ce_oi, pe_oi) VALUES (?, ?, ?, ?, ?, ?)", 
                   (idx, date_str, t_str, pcr, ce_oi, pe_oi))


def run_pcr_thread():
    """Sample PCR every 60 seconds during market hours (09:00–15:35 IST)."""
    import time as _time
    while True:
        now = datetime.datetime.now()
        if now.hour >= 9 and (now.hour < 15 or (now.hour == 15 and now.minute <= 35)):
            try:
                snapshot_pcr()
            except Exception as e:
                print(f"[PCR] Snapshot error: {e}")
        _time.sleep(60)


@app.route('/pcr')
@login_required
def pcr_page(): return render_template('pcr.html')


@app.route('/api/pcr_history')
@login_required
def pcr_history_api():
    idx = request.args.get('index', 'NIFTY').upper()
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    rows = db_query("SELECT time as t, pcr, ce_oi, pe_oi FROM pcr_logs WHERE index_name=? AND date=? ORDER BY time ASC", (idx, date_str))
    return jsonify([dict(r) for r in rows])


@app.route('/api/pcr_snapshot', methods=['POST'])
@login_required
def pcr_snapshot_now():
    """Force an immediate PCR snapshot (called from frontend on page load)."""
    try:
        snapshot_pcr()
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    return jsonify({'status': 'ok'})


# --- GREEKS & CHAIN ---
def fetch_api_greeks(name, expiry):
    global smartApi
    try:
        if not smartApi: return None
        payload = { "name": name, "expirydate": expiry }
        response = smartApi._postRequest("api.market.optiongreeks", payload)
        if response and response.get('status') and response.get('data'):
            greeks_map = {}
            for item in response['data']:
                k = (float(item['strikePrice']), item['optionType'])
                greeks_map[k] = {
                    'delta': item.get('delta', 0), 'gamma': item.get('gamma', 0),
                    'theta': item.get('theta', 0), 'vega': item.get('vega', 0),
                    'iv': item.get('impliedVolatility', 0)
                }
            return greeks_map
    except Exception: return None
    return None

def calculate_greeks(S, K, T, r, sigma, option_type):
    if S <= 0 or K <= 0 or T <= 0: return {'delta':0, 'gamma':0, 'theta':0, 'vega':0, 'iv': sigma*100}
    try:
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        delta = norm.cdf(d1) if option_type == 'CE' else norm.cdf(d1) - 1
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        theta = (-(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))) / 365.0 
        vega = (S * norm.pdf(d1) * np.sqrt(T)) / 100.0
        return {'delta': round(delta, 3), 'gamma': round(gamma, 5), 'theta': round(theta, 2), 'vega': round(vega, 2), 'iv': round(sigma*100, 2)}
    except: return {'delta':0, 'gamma':0, 'theta':0, 'vega':0, 'iv':0}

@app.route('/api/option_chain', methods=['POST'])
def chain_data():
    spot = float(request.json.get('spot'))
    expiry_str = request.json.get('expiry')
    idx = request.json.get('index', 'NIFTY')
    step = 50
    if idx in ['SENSEX', 'BANKEX', 'BANKNIFTY']: step = 100
    if idx == 'MIDCPNIFTY': step = 25
    atm = round(spot / step) * step
    range_mult = 20 if idx in ['SENSEX', 'BANKEX'] else 10
    min_strike = atm - (step * range_mult)
    max_strike = atm + (step * range_mult)
    
    chain = db_query("SELECT * FROM scrips WHERE name=? AND expiry=? AND strike BETWEEN ? AND ?", (idx, expiry_str, min_strike, max_strike))
    
    api_expiry = expiry_str.upper()
    api_greeks = fetch_api_greeks(idx, api_expiry)
    T = 0.02
    res = defaultdict(dict)
    for row in chain:
        strike = row['strike']
        row_dict = dict(row)
        key = (float(strike), row['type'])
        if api_greeks and key in api_greeks: row_dict.update(api_greeks[key])
        else: row_dict.update(calculate_greeks(spot, strike, T, 0.07, 0.20, row['type']))
        res[strike][row['type']] = row_dict
    return jsonify({'atm': atm, 'chain': [{'strike':s, 'CE':res[s].get('CE'), 'PE':res[s].get('PE')} for s in sorted(res.keys())]})

@app.route('/api/expiries', methods=['POST'])
def expiries():
    idx = request.json.get('index', 'NIFTY')
    rows = db_query("SELECT DISTINCT expiry FROM scrips WHERE name=?", (idx,))

    def parse_date(d_str):
        try: return datetime.datetime.strptime(d_str, "%d%b%Y").date()
        except: return datetime.date.max

    # Sort all valid expiry strings by date
    all_dates = sorted(
        [(r['expiry'], parse_date(r['expiry'])) for r in rows if r['expiry']],
        key=lambda x: x[1]
    )

    # Group expiries by (year, month) to classify weekly vs monthly
    from collections import defaultdict
    month_buckets = defaultdict(list)
    for d_str, d in all_dates:
        if d != datetime.date.max:
            month_buckets[(d.year, d.month)].append((d, d_str))

    classified = []
    for (year, month), items in sorted(month_buckets.items()):
        items_sorted = sorted(items)  # sort by date within the month
        count = len(items_sorted)
        for i, (d, d_str) in enumerate(items_sorted):
            if i == count - 1:
                # Last expiry of the month → monthly
                exp_type = 'monthly'
            else:
                exp_type = 'weekly'
            classified.append({'date': d_str, 'type': exp_type})

    return jsonify(classified)

# --- CONNECTION & PROCESS TICK ---
def connect_angel():
    global sws, smartApi
    try:
        if not API_KEY or not CLIENT_CODE:
            print("❌ Missing API Credentials in .env")
            return
        smartApi = SmartConnect(api_key=API_KEY)
        t = smartApi.generateSession(CLIENT_CODE, PIN, pyotp.TOTP(TOTP_KEY).now())
        if t['status']:
            if "api.market.optiongreeks" not in smartApi._routes:
                smartApi._routes["api.market.optiongreeks"] = "rest/secure/angelbroking/marketData/v1/optionGreek"
            sws = SmartWebSocketV2(t['data']['jwtToken'], API_KEY, CLIENT_CODE, t['data']['feedToken'])
            sws.on_data = lambda ws, msg: process_tick(msg)
            sws.connect()
    except Exception as e: print(f"❌ Login Error: {e}")

def process_tick(msg):
    if 'token' in msg:
        t = msg['token']
        curr = LIVE_FEED.get(t, {'ltp': 0, 'close': 0, 'pct': "0.00%", 'vol': 0, 'atp': 0, 'oi': 0})
        
        if 'last_traded_price' in msg:
            l = float(msg['last_traded_price']) / 100
            curr['ltp'] = l
            c = curr['close']
            if c == 0 and 'close_price' in msg:
                c = float(msg['close_price']) / 100
                curr['close'] = c
            if c > 0: curr['pct'] = f"{((l-c)/c)*100:+.2f}%"

        if 'vol_traded' in msg: curr['vol'] = msg['vol_traded']
        elif 'volume_trade_for_the_day' in msg: curr['vol'] = msg['volume_trade_for_the_day']
        elif 'volume' in msg: curr['vol'] = msg['volume']
            
        if 'avg_traded_price' in msg: curr['atp'] = float(msg['avg_traded_price']) / 100
        elif 'average_traded_price' in msg: curr['atp'] = float(msg['average_traded_price']) / 100
        elif 'atp' in msg: curr['atp'] = float(msg['atp']) / 100
            
        if 'open_interest' in msg: curr['oi'] = msg['open_interest']
        elif 'oi' in msg: curr['oi'] = msg['oi']
            
        LIVE_FEED[t] = curr

# ====================================================
# APP INITIALIZATION
# ====================================================
init_db()

# Prevent threads from spawning multiple times if a WSGI worker restarts
if not os.environ.get("THREADS_STARTED"):
    threading.Thread(target=fetch_tokens.update_master_db, daemon=False).start() 
    threading.Thread(target=connect_angel, daemon=True).start()
    threading.Thread(target=monitor_positions, daemon=True).start()
    threading.Thread(target=monitor_traffic, daemon=True).start()
    threading.Thread(target=run_pcr_thread, daemon=True).start()
    os.environ["THREADS_STARTED"] = "1"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)