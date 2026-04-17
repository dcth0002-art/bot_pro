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

# --- CẤU HÌNH BOT ---
COIN_PAIRS_TO_TRADE = [
    # Top-tier
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", 
    # Major Alts
    "XRP-USDT-SWAP", "DOGE-USDT-SWAP", "ADA-USDT-SWAP", 
    "AVAX-USDT-SWAP", "DOT-USDT-SWAP", "MATIC-USDT-SWAP",
    "LTC-USDT-SWAP", "BCH-USDT-SWAP", "LINK-USDT-SWAP",
    # High-Volume
    "OP-USDT-SWAP", "ARB-USDT-SWAP", "NEAR-USDT-SWAP",
    "AAVE-USDT-SWAP", "UNI-USDT-SWAP", "FTM-USDT-SWAP",
    # Trending/Popular
    "WLD-USDT-SWAP", "PEPE-USDT-SWAP", "SUI-USDT-SWAP",
    "FIL-USDT-SWAP", "ETC-USDT-SWAP", "ICP-USDT-SWAP",
    "TON-USDT-SWAP"
]
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
    # (Hàm này giữ nguyên)
    pass

def get_historical_data(instId, timeframe, limit=100):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={instId}&bar={timeframe}&limit={limit}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json().get('data', [])
        if not data:
            return None
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote', 'confirm'])
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.sort_values(by='timestamp', ascending=False).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"Lỗi khi lấy dữ liệu lịch sử cho {instId}: {e}")
        return None
# --- KẾT THÚC CÁC HÀM TIỆN ÍCH ---

# --- LỚP QUẢN LÝ GIAO DỊCH ---
class TradeManager:
    # (Lớp này giữ nguyên)
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
                pnl = self.close_position(coin, pos['sl'] if reason == "Stoploss" else pos['tp'])
                closed_trades.append({"coin": coin, "pnl": pnl, "reason": reason})
        return closed_trades
# --- KẾT THÚC LỚP QUẢN LÝ ---

# --- HÀM CHÍNH CỦA BOT ---
def run_bot():
    manager = TradeManager(DEMO_BALANCE_USD)
    send_telegram_message(f"🚀 *Bot Giao Dịch PRO (v2.3) đã khởi động* 🚀\nVốn ban đầu: ${manager.balance:.2f}\nChiến lược: EMA, RSI, MACD, OBV")

    while True:
        print(f"\n[{time.strftime('%H:%M:%S')}] Bắt đầu chu kỳ quét... Số dư: ${manager.balance:.2f}, Lệnh mở: {len(manager.open_positions)}")
        
        current_prices = {}
        for coin in COIN_PAIRS_TO_TRADE:
            df_price = get_historical_data(coin, "1m", 2)
            if df_price is not None:
                current_prices[coin] = df_price['close'].iloc[0]

        # Kiểm tra và đóng các vị thế chạm SL/TP
        closed_trades = manager.check_positions(current_prices)
        
        # Gửi thông báo cho từng lệnh đã đóng
        for trade in closed_trades:
            msg = (f"🔴 *LỆNH ĐÃ ĐÓNG ({trade['reason']})*\n\n"
                   f"Cặp tiền: *{trade['coin']}*\n"
                   f"Lời/Lỗ: *${trade['pnl']:.2f}*\n"
                   f"Số dư mới: `${manager.balance:.2f}`")
            send_telegram_message(msg)
            print(msg)

        # Nếu có lệnh vừa đóng, gửi báo cáo tổng quan ngay lập tức
        if closed_trades:
            print("Một hoặc nhiều lệnh đã đóng, gửi báo cáo tổng quan...")
            pnl = manager.balance - DEMO_BALANCE_USD
            pnl_percent = (pnl / DEMO_BALANCE_USD) * 100
            pnl_sign = "+" if pnl >= 0 else ""
            
            report_message = (
                f"📊 *BÁO CÁO TỔNG QUAN (Sau khi đóng lệnh)*\n\n"
                f"‣ *Số dư hiện tại:* `${manager.balance:,.2f}`\n"
                f"‣ *Lời/Lỗ (PNL):* `{pnl_sign}${pnl:,.2f}` (`{pnl_sign}{pnl_percent:.2f}%`)\n"
                f"‣ *Số lệnh đang mở:* `{len(manager.open_positions)}`"
            )
            send_telegram_message(report_message)
            print(report_message)

        # Phân tích và tìm tín hiệu mới
        for coin in COIN_PAIRS_TO_TRADE:
            if coin in manager.open_positions:
                continue

            df = get_historical_data(coin, TIMEFRAME)
            if df is None or len(df) < 35:
                continue

            # --- TÍNH TOÁN TẤT CẢ CÁC CHỈ BÁO ---
            df.ta.ema(length=10, append=True)
            df.ta.ema(length=30, append=True)
            df.ta.rsi(length=14, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.obv(append=True)
            df.ta.atr(length=14, append=True)
            
            latest = df.iloc[0]
            prev = df.iloc[1]

            # --- KIỂM TRA ĐIỀU KIỆN MUA ---
            buy_conditions = [
                latest['EMA_10'] > latest['EMA_30'],
                latest['RSI_14'] < STRONG_SIGNAL_RSI_OVERSOLD,
                latest['MACD_12_26_9'] > latest['MACDs_12_26_9'] and prev['MACD_12_26_9'] < prev['MACDs_12_26_9'],
                latest['OBV'] > prev['OBV']
            ]

            # --- KIỂM TRA ĐIỀU KIỆN BÁN ---
            sell_conditions = [
                latest['EMA_10'] < latest['EMA_30'],
                latest['RSI_14'] > STRONG_SIGNAL_RSI_OVERBOUGHT,
                latest['MACD_12_26_9'] < latest['MACDs_12_26_9'] and prev['MACD_12_26_9'] > prev['MACDs_12_26_9'],
                latest['OBV'] < prev['OBV']
            ]

            side = None
            if all(buy_conditions): side = 'buy'
            elif all(sell_conditions): side = 'sell'

            if side:
                price = latest['close']
                atr = latest['ATRr_14']
                
                atr_percentage = (atr / price) * 100
                volatility = "medium_volatility"
                if atr_percentage > ATR_VOLATILITY_THRESHOLD_HIGH: volatility = "high_volatility"
                elif atr_percentage < ATR_VOLATILITY_THRESHOLD_LOW: volatility = "low_volatility"
                config = RISK_CONFIG[volatility]

                if side == 'buy':
                    sl = price - (config['sl_multiplier'] * atr)
                    tp = price + (config['tp_multiplier'] * atr)
                    reason = "EMA(bull) & RSI(OB) & MACD(cross_up) & OBV(up)"
                    msg_header = "🟢 *LỆNH MUA MỚI (Tín hiệu hội tụ)*"
                else: # sell
                    sl = price + (config['sl_multiplier'] * atr)
                    tp = price - (config['tp_multiplier'] * atr)
                    reason = "EMA(bear) & RSI(OS) & MACD(cross_down) & OBV(down)"
                    msg_header = "🟠 *LỆNH BÁN MỚI (Tín hiệu hội tụ)*"
                
                if manager.open_position(coin, side, price, POSITION_SIZE_USD, config['leverage'], sl, tp):
                    msg = (f"{msg_header}\n\n"
                           f"Cặp tiền: *{coin}*\n"
                           f"Lý do: *{reason}*\n"
                           f"Giá vào lệnh: `${price:,.4f}`\n"
                           f"Đòn bẩy: *x{config['leverage']}* ({volatility})\n"
                           f"Stoploss: `${sl:,.4f}`\n"
                           f"Take Profit: `${tp:,.4f}`")
                    send_telegram_message(msg)
                    print(msg)

        time.sleep(60 * 5)

if __name__ == "__main__":
    if not all([API_KEY, SECRET_KEY, PASSPHRASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        print("LỖI: Vui lòng cung cấp đầy đủ các biến môi trường.")
    else:
        run_bot()
