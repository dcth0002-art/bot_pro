import ccxt
import time
import os
import telebot
from dotenv import load_dotenv
from collections import deque

# Load biến môi trường
load_dotenv()

# --- CẤU HÌNH ---
SYMBOLS = [
    'BTC/USDT', 'JTO/USDT', 'ETH/USDT', 'DOGE/USDT', 
    'SOL/USDT', 'XRP/USDT', 'BCH/USDT', 'LTC/USDT',
    'OKB/USDT', 'KAITO/USDT', 'PI/USDT'
]
LEVERAGE = 10
DEFAULT_TRADE_AMOUNT = 100
INITIAL_BALANCE = 100
CHECK_INTERVAL = 1
WARMUP_PERIOD = 300 
VOL_WINDOW_SIZE = 1800 
COOLDOWN_PERIOD = 300 # Tăng lên 5 phút để tránh bị cuốn vào sideway
VOL_DIFF_THRESHOLD = 0.50 
CONFIRMATION_TIME = 60 
PRICE_SURGE_THRESHOLD = 0.001 # 0.1% (tương đương 1% trên đòn bẩy 10x)
STATUS_REPORT_INTERVAL = 600 

# --- THÔNG TIN TELEGRAM ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

exchange = ccxt.okx() 
bot = telebot.TeleBot(TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

def send_telegram(message):
    print(message)
    if bot and TELEGRAM_CHAT_ID:
        try:
            bot.send_message(TELEGRAM_CHAT_ID, message, parse_mode='Markdown')
        except Exception as e:
            print(f"Lỗi gửi Telegram: {e}")

class TradingBot:
    def __init__(self):
        self.balance = INITIAL_BALANCE
        self.current_position = None
        self.active_symbol = None
        self.entry_price = 0
        self.amount_coin = 0
        
        self.coins = {}
        for symbol in SYMBOLS:
            self.coins[symbol] = {
                'vol_trades': deque(),
                'last_trade_id': None,
                'price_history': deque(maxlen=310),
                'pending_side': None,
                'trigger_price': 0,
                'trigger_time': 0,
                'last_close_time': 0,
                'total_buy_30p': 0.0,
                'total_sell_30p': 0.0
            }
        
        self.start_time = time.time()
        self.last_status_time = time.time()
        self.is_warmed_up = False

    def update_coin_data(self, symbol):
        try:
            c = self.coins[symbol]
            current_time = time.time()
            trades = exchange.fetch_trades(symbol, limit=50) 
            new_trades = []
            if c['last_trade_id'] is None:
                new_trades = trades
            else:
                for trade in reversed(trades):
                    if trade['id'] == c['last_trade_id']:
                        break
                    new_trades.insert(0, trade)
            if new_trades:
                for t in new_trades:
                    c['vol_trades'].append((t['timestamp'] / 1000, t['side'], t['amount']))
                c['last_trade_id'] = new_trades[-1]['id']

            cutoff = current_time - VOL_WINDOW_SIZE
            while c['vol_trades'] and c['vol_trades'][0][0] < cutoff:
                c['vol_trades'].popleft()

            c['total_buy_30p'] = sum(t[2] for t in c['vol_trades'] if t[1] == 'buy')
            c['total_sell_30p'] = sum(t[2] for t in c['vol_trades'] if t[1] == 'sell')

            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            c['price_history'].append(current_price)
            return current_price
        except Exception as e:
            print(f"Lỗi cập nhật {symbol}: {e}")
            return None

    def run(self):
        send_telegram(f"🚀 *Bot Săn Lệnh Cao Cấp đã khởi động!*\n- Yêu cầu bùng nổ: `0.1%` trong 60s\n- Nghỉ sau lệnh: `5 phút` để diệt nhiễu.")
        
        while True:
            current_time = time.time()
            if not self.is_warmed_up:
                if current_time - self.start_time >= WARMUP_PERIOD:
                    self.is_warmed_up = True
                    send_telegram("✅ *Tích lũy xong!* Bắt đầu săn tìm cơ hội.")
                else:
                    for sym in SYMBOLS:
                        self.update_coin_data(sym)
                        time.sleep(0.05)
                    continue

            if self.active_symbol is None:
                for symbol in SYMBOLS:
                    current_price = self.update_coin_data(symbol)
                    if current_price is None: continue
                    
                    c = self.coins[symbol]
                    price_trend_ago = c['price_history'][-180] if len(c['price_history']) >= 180 else c['price_history'][0]
                    buy_diff = (c['total_buy_30p'] - c['total_sell_30p']) / c['total_sell_30p'] if c['total_sell_30p'] > 0 else 1.0
                    sell_diff = (c['total_sell_30p'] - c['total_buy_30p']) / c['total_buy_30p'] if c['total_buy_30p'] > 0 else 1.0

                    if current_time - c['last_close_time'] >= COOLDOWN_PERIOD:
                        if c['pending_side'] is None:
                            if buy_diff > VOL_DIFF_THRESHOLD and current_price > price_trend_ago:
                                c['pending_side'] = 'buy'
                                c['trigger_price'] = current_price
                                c['trigger_time'] = current_time
                                print(f"🔍 [{symbol}] Vol Mua mạnh! Chờ xác nhận bùng nổ...")
                            elif sell_diff > VOL_DIFF_THRESHOLD and current_price < price_trend_ago:
                                c['pending_side'] = 'sell'
                                c['trigger_price'] = current_price
                                c['trigger_time'] = current_time
                                print(f"🔍 [{symbol}] Vol Bán mạnh! Chờ xác nhận bùng nổ...")
                        else:
                            elapsed = current_time - c['trigger_time']
                            # Tính % thay đổi so với giá đánh dấu
                            price_change = (current_price - c['trigger_price']) / c['trigger_price']
                            
                            if c['pending_side'] == 'buy':
                                if current_price < c['trigger_price']:
                                    c['pending_side'] = None # Hủy vì giá quay đầu
                                elif elapsed >= CONFIRMATION_TIME:
                                    if price_change >= PRICE_SURGE_THRESHOLD:
                                        self.open_position(symbol, 'buy', current_price, buy_diff, price_change)
                                        break
                                    else:
                                        print(f"❌ [{symbol}] Hết 60s giá chỉ tăng {price_change*100:.2f}%, quá yếu.")
                                        c['pending_side'] = None
                            
                            elif c['pending_side'] == 'sell':
                                if current_price > c['trigger_price']:
                                    c['pending_side'] = None
                                elif elapsed >= CONFIRMATION_TIME:
                                    if abs(price_change) >= PRICE_SURGE_THRESHOLD:
                                        self.open_position(symbol, 'sell', current_price, sell_diff, price_change)
                                        break
                                    else:
                                        print(f"❌ [{symbol}] Hết 60s giá chỉ giảm {abs(price_change)*100:.2f}%, quá yếu.")
                                        c['pending_side'] = None
                    time.sleep(0.05)

            else:
                symbol = self.active_symbol
                current_price = self.update_coin_data(symbol)
                if current_price:
                    c = self.coins[symbol]
                    price_trend_ago = c['price_history'][-180] if len(c['price_history']) >= 180 else c['price_history'][0]
                    if self.current_position == 'buy':
                        if current_price <= price_trend_ago:
                            self.close_position(current_price, f"Giá {symbol} đảo chiều 3p")
                    elif self.current_position == 'sell':
                        if current_price >= price_trend_ago:
                            self.close_position(current_price, f"Giá {symbol} đảo chiều 3p")

            if current_time - self.last_status_time >= STATUS_REPORT_INTERVAL:
                self.send_multi_report()
                self.last_status_time = current_time
            time.sleep(CHECK_INTERVAL)

    def open_position(self, symbol, side, price, diff, change):
        self.active_symbol = symbol
        self.current_position = side
        self.entry_price = price
        trade_amt = min(self.balance, DEFAULT_TRADE_AMOUNT)
        self.amount_coin = (trade_amt * LEVERAGE) / price
        emoji = "🟢" if side == 'buy' else "🔴"
        msg = (
            f"{emoji} *VÀO LỆNH {side.upper()} ({symbol})*\n"
            f"💰 Giá: `{price:,.4f}`\n"
            f"🚀 Bùng nổ: `{change*100:.2f}%` (trong 60s)\n"
            f"📊 Vol 30p: `+{diff*100:.1f}%` 🔥\n"
            f"💵 Quy mô: `${trade_amt:,.2f}` (x{LEVERAGE})"
        )
        send_telegram(msg)
        for s in SYMBOLS: self.coins[s]['pending_side'] = None

    def close_position(self, price, reason):
        symbol = self.active_symbol
        pnl = (price - self.entry_price) * self.amount_coin if self.current_position == 'buy' else (self.entry_price - price) * self.amount_coin
        self.balance += pnl
        self.coins[symbol]['last_close_time'] = time.time()
        status = "LÃI" if pnl > 0 else "LỖ"
        msg = (
            f"⚠️ *ĐÓNG LỆNH {symbol}*\n"
            f"📝 Lý do: {reason}\n"
            f"🏁 PnL: `{pnl:,.2f}$` ({status})\n"
            f"🏦 Số dư: `${self.balance:,.2f}$`"
        )
        send_telegram(msg)
        self.active_symbol = None
        self.current_position = None

    def send_multi_report(self):
        msg = f"📊 *GIÁM SÁT HỆ THỐNG*\n📍 {'Đang trade: ' + self.active_symbol if self.active_symbol else 'Đang săn tín hiệu...'}\n🏦 Vốn: `${self.balance:,.2f}$`"
        send_telegram(msg)

if __name__ == "__main__":
    bot_trading = TradingBot()
    try:
        bot_trading.run()
    except KeyboardInterrupt:
        send_telegram("🛑 *Bot đã dừng.*")
