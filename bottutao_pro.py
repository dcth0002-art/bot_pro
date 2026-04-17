import os
import time
import requests
import pandas as pd
import pandas_ta as ta

# --- LẤY THÔNG TIN TỪ BIẾN MÔI TRƯỜNG ---
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
PASSPHRASE = os.getenv("PASSPHRASE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# --- KẾT THÚC LẤY THÔNG TIN ---

# --- HÀM TẢI DANH SÁCH COIN ---
def load_coin_list():
    """Tải danh sách coin từ file coin_list.txt."""
    try:
        with open("coin_list.txt", "r") as f:
            coins = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        print(f"Đã tải {len(coins)} đồng coin từ coin_list.txt")
        return coins
    except FileNotFoundError:
        print("Không tìm thấy file coin_list.txt. Sử dụng danh sách mặc định.")
        return ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
# --- KẾT THÚC HÀM TẢI DANH SÁCH COIN ---


# --- CẤU HÌNH BOT ---
COIN_PAIRS_TO_TRADE = load_coin_list()
TIMEFRAME = "15m"
DEMO_BALANCE_USD = 500.0
POSITION_SIZE_USD = 50.0
STRONG_SIGNAL_RSI_OVERSOLD = 25
STRONG_SIGNAL_RSI_OVERBOUGHT = 75
ATR_VOLATILITY_THRESHOLD_HIGH = 1.5
ATR_VOLATILITY_THRESHOLD_LOW = 0.5

RISK_CONFIG = {
    "high_volatility": {"leverage": 3, "sl_multiplier": 2.5, "tp_multiplier": 5.0},
    "medium_volatility": {"leverage": 5, "sl_multiplier": 2.0, "tp_multiplier": 4.0},
    "low_volatility": {"leverage": 10, "sl_multiplier": 1.5, "tp_multiplier": 3.0}
}
# --- KẾT THÚC CẤU HÌNH ---

# --- CÁC HÀM TIỆN ÍCH ---
def send_telegram_message(message):
    """Gửi tin nhắn đến Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, json=payload, timeout=5)
    except: pass

def get_all_tickers():
    """Lấy giá của TẤT CẢ các cặp SWAP trên OKX trong 1 lần gọi duy nhất."""
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        response = requests.get(url, timeout=10)
        data = response.json().get('data', [])
        return {item['instId']: float(item['last']) for item in data}
    except Exception as e:
        print(f"Lỗi khi lấy giá hàng loạt: {e}")
        return {}

def get_historical_data(instId, timeframe, limit=100):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={instId}&bar={timeframe}&limit={limit}"
        response = requests.get(url, timeout=10)
        data = response.json().get('data', [])
        if not data: return None
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote', 'confirm'])
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.sort_values(by='timestamp', ascending=False).reset_index(drop=True)
        return df
    except: return None
# --- KẾT THÚC CÁC HÀM TIỆN ÍCH ---

class TradeManager:
    def __init__(self, initial_balance):
        self.balance = initial_balance
        self.open_positions = {}

    def open_position(self, coin_pair, side, price, size, leverage, sl, tp):
        if coin_pair in self.open_positions: return False
        cost = size / leverage
        if self.balance < cost: return False
        self.balance -= cost
        self.open_positions[coin_pair] = {"side": side, "entry_price": price, "size": size, "leverage": leverage, "sl": sl, "tp": tp, "margin": cost}
        return True

    def close_position(self, coin_pair, exit_price):
        if coin_pair not in self.open_positions: return None
        pos = self.open_positions.pop(coin_pair)
        pnl = ((exit_price - pos['entry_price']) / pos['entry_price']) * pos['size'] if pos['side'] == 'buy' else ((pos['entry_price'] - exit_price) / pos['entry_price']) * pos['size']
        self.balance += (pos['margin'] + pnl)
        return pnl

    def check_positions(self, current_prices):
        closed_trades = []
        for coin, pos in list(self.open_positions.items()):
            price = current_prices.get(coin)
            if not price: continue
            reason = ""
            if (pos['side'] == 'buy' and price <= pos['sl']) or (pos['side'] == 'sell' and price >= pos['sl']):
                reason = "Stoploss"
            elif (pos['side'] == 'buy' and price >= pos['tp']) or (pos['side'] == 'sell' and price <= pos['tp']):
                reason = "Take Profit"
            if reason:
                # Lấy giá khớp thực tế (giá chặn lỗ hoặc chốt lời)
                exit_price = pos['sl'] if reason == "Stoploss" else pos['tp']
                pnl = self.close_position(coin, exit_price)
                closed_trades.append({"coin": coin, "pnl": pnl, "reason": reason})
        return closed_trades

# --- HÀM CHÍNH ---
def run_bot():
    manager = TradeManager(DEMO_BALANCE_USD)
    send_telegram_message(f"🚀 *Bot PRO v2.6.1 đã khởi động*\nVốn: `${manager.balance:.2f}`\nTheo dõi: {len(COIN_PAIRS_TO_TRADE)} cặp.")

    while True:
        start_time = time.time()
        print(f"\n[{time.strftime('%H:%M:%S')}] Chu kỳ mới. Lệnh mở: {len(manager.open_positions)}")
        
        # 1. Lấy giá toàn sàn
        current_prices = get_all_tickers()
        
        # 2. Kiểm tra đóng lệnh
        closed_trades = manager.check_positions(current_prices)
        for trade in closed_trades:
            msg = (f"🔴 *LỆNH ĐÃ ĐÓNG ({trade['reason']})*\n\n"
                   f"Cặp tiền: *{trade['coin']}*\n"
                   f"Lời/Lỗ: *${trade['pnl']:.2f}*\n"
                   f"Số dư mới: `${manager.balance:.2f}`")
            send_telegram_message(msg)
            print(msg)

        if closed_trades:
            pnl_total = manager.balance - DEMO_BALANCE_USD
            pnl_percent = (pnl_total / DEMO_BALANCE_USD) * 100
            pnl_sign = "+" if pnl_total >= 0 else ""
            report = (f"📊 *BÁO CÁO TỔNG QUAN*\n\n"
                      f"‣ *Số dư hiện tại:* `${manager.balance:,.2f}`\n"
                      f"‣ *Tổng PNL:* `{pnl_sign}${pnl_total:,.2f}` (`{pnl_sign}{pnl_percent:.2f}%`)\n"
                      f"‣ *Số lệnh đang mở:* `{len(manager.open_positions)}`")
            send_telegram_message(report)
            print(report)

        # 3. Quét tìm cơ hội mới
        for coin in COIN_PAIRS_TO_TRADE:
            if coin in manager.open_positions: continue
            
            time.sleep(0.05) 
            df = get_historical_data(coin, TIMEFRAME)
            if df is None or len(df) < 35: continue

            # Phân tích kỹ thuật
            df.ta.ema(length=10, append=True)
            df.ta.ema(length=30, append=True)
            df.ta.rsi(length=14, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.obv(append=True)
            df.ta.atr(length=14, append=True)
            
            latest = df.iloc[0]
            prev = df.iloc[1]

            buy_cond = [
                latest['EMA_10'] > latest['EMA_30'],
                latest['RSI_14'] < STRONG_SIGNAL_RSI_OVERSOLD,
                latest['MACD_12_26_9'] > latest['MACDs_12_26_9'] and prev['MACD_12_26_9'] < prev['MACDs_12_26_9'],
                latest['OBV'] > prev['OBV']
            ]

            sell_cond = [
                latest['EMA_10'] < latest['EMA_30'],
                latest['RSI_14'] > STRONG_SIGNAL_RSI_OVERBOUGHT,
                latest['MACD_12_26_9'] < latest['MACDs_12_26_9'] and prev['MACD_12_26_9'] > prev['MACDs_12_26_9'],
                latest['OBV'] < prev['OBV']
            ]

            side = 'buy' if all(buy_cond) else 'sell' if all(sell_cond) else None

            if side:
                price = latest['close']
                atr = latest['ATRr_14']
                atr_p = (atr / price) * 100
                vol = "high_volatility" if atr_p > ATR_VOLATILITY_THRESHOLD_HIGH else "low_volatility" if atr_p < ATR_VOLATILITY_THRESHOLD_LOW else "medium_volatility"
                config = RISK_CONFIG[vol]

                sl = price - (config['sl_multiplier'] * atr) if side == 'buy' else price + (config['sl_multiplier'] * atr)
                tp = price + (config['tp_multiplier'] * atr) if side == 'buy' else price - (config['tp_multiplier'] * atr)
                
                if manager.open_position(coin, side, price, POSITION_SIZE_USD, config['leverage'], sl, tp):
                    msg = (f"🟢 *LỆNH {side.upper()} MỚI*\n\n"
                           f"Cặp tiền: *{coin}*\n"
                           f"Giá vào: `${price:,.4f}`\n"
                           f"Đòn bẩy: *x{config['leverage']}* ({vol})\n"
                           f"SL: `${sl:,.4f}` | TP: `${tp:,.4f}`")
                    send_telegram_message(msg)
                    print(msg)

        elapsed = time.time() - start_time
        print(f"Hoàn thành chu kỳ trong {elapsed:.2f}s")
        time.sleep(max(1, 30 - elapsed) if elapsed < 30 else 5)

if __name__ == "__main__":
    if not all([API_KEY, SECRET_KEY, PASSPHRASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        print("LỖI: Thiếu biến môi trường.")
    else:
        run_bot()
