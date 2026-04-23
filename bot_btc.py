import ccxt
import time
import os
import telebot
from dotenv import load_dotenv
from collections import deque

# Load biến môi trường
load_dotenv()

# --- CẤU HÌNH ---
SYMBOL = 'BTC/USDT'
LEVERAGE = 10
DEFAULT_TRADE_AMOUNT = 100
INITIAL_BALANCE = 100
CHECK_INTERVAL = 1
WARMUP_PERIOD = 300 
VOL_WINDOW_SIZE = 1800 
COOLDOWN_PERIOD = 180 
VOL_DIFF_THRESHOLD = 0.50 
CONFIRMATION_TIME = 60 # 60 giây xác nhận giá sau khi đủ Vol
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
        self.entry_price = 0
        self.amount_coin = 0
        self.current_trade_amount = 0
        
        self.vol_trades = deque()
        self.last_trade_id = None
        self.total_buy_30p = 0.0
        self.total_sell_30p = 0.0
        
        self.start_time = time.time()
        self.last_close_time = 0
        self.last_status_time = time.time()
        self.is_warmed_up = False
        
        # Biến phục vụ xác nhận 60s
        self.pending_side = None
        self.trigger_price = 0
        self.trigger_time = 0
        
        self.price_history = deque(maxlen=310) 

    def update_data(self):
        try:
            current_time = time.time()
            trades = exchange.fetch_trades(SYMBOL, limit=100)
            new_trades = []
            if self.last_trade_id is None:
                new_trades = trades
            else:
                for trade in reversed(trades):
                    if trade['id'] == self.last_trade_id:
                        break
                    new_trades.insert(0, trade)
            
            if new_trades:
                for t in new_trades:
                    self.vol_trades.append((t['timestamp'] / 1000, t['side'], t['amount']))
                self.last_trade_id = new_trades[-1]['id']

            cutoff = current_time - VOL_WINDOW_SIZE
            while self.vol_trades and self.vol_trades[0][0] < cutoff:
                self.vol_trades.popleft()

            self.total_buy_30p = sum(t[2] for t in self.vol_trades if t[1] == 'buy')
            self.total_sell_30p = sum(t[2] for t in self.vol_trades if t[1] == 'sell')

            ticker = exchange.fetch_ticker(SYMBOL)
            current_price = ticker['last']
            self.price_history.append(current_price)
            
            return current_price
        except Exception as e:
            print(f"Lỗi cập nhật dữ liệu: {e}")
            return None

    def run(self):
        send_telegram(f"🚀 *Bot BTC/USDT (Xác nhận 60s) đã khởi động!*\n- Đợi Vol > 50% -> Đánh dấu giá -> Chờ 60s ổn định giá để vào lệnh.")
        
        while True:
            current_price = self.update_data()
            if current_price is None:
                time.sleep(CHECK_INTERVAL)
                continue

            current_time = time.time()
            if not self.is_warmed_up:
                if current_time - self.start_time >= WARMUP_PERIOD:
                    self.is_warmed_up = True
                    send_telegram("✅ *Tích lũy xong!* Bắt đầu quét tín hiệu.")
                else:
                    time.sleep(CHECK_INTERVAL)
                    continue

            price_trend_ago = self.price_history[-180] if len(self.price_history) >= 180 else self.price_history[0]
            buy_diff = (self.total_buy_30p - self.total_sell_30p) / self.total_sell_30p if self.total_sell_30p > 0 else 1.0
            sell_diff = (self.total_sell_30p - self.total_buy_30p) / self.total_buy_30p if self.total_buy_30p > 0 else 1.0

            # LOGIC GIAO DỊCH
            if self.current_position is None:
                if current_time - self.last_close_time >= COOLDOWN_PERIOD:
                    
                    # 1. Bắt đầu giai đoạn chờ xác nhận nếu chưa có
                    if self.pending_side is None:
                        if buy_diff > VOL_DIFF_THRESHOLD and current_price > price_trend_ago:
                            self.pending_side = 'buy'
                            self.trigger_price = current_price
                            self.trigger_time = current_time
                            print(f"🔍 Phát hiện Vol Mua mạnh! Đánh dấu giá {current_price}, chờ 60s...")
                        elif sell_diff > VOL_DIFF_THRESHOLD and current_price < price_trend_ago:
                            self.pending_side = 'sell'
                            self.trigger_price = current_price
                            self.trigger_time = current_time
                            print(f"🔍 Phát hiện Vol Bán mạnh! Đánh dấu giá {current_price}, chờ 60s...")
                    
                    # 2. Đang trong 60s xác nhận
                    else:
                        elapsed_confirm = current_time - self.trigger_time
                        
                        if self.pending_side == 'buy':
                            # Nếu giá rớt xuống dưới giá đánh dấu -> Hủy xác nhận
                            if current_price < self.trigger_price:
                                print(f"❌ Giá rớt dưới mốc {self.trigger_price}, hủy xác nhận LONG.")
                                self.pending_side = None
                            elif elapsed_confirm >= CONFIRMATION_TIME:
                                # Đã đủ 60s và giá vẫn tốt -> VÀO LỆNH
                                self.open_position('buy', current_price, buy_diff)
                                self.pending_side = None
                        
                        elif self.pending_side == 'sell':
                            # Nếu giá tăng lên trên giá đánh dấu -> Hủy xác nhận
                            if current_price > self.trigger_price:
                                print(f"❌ Giá tăng trên mốc {self.trigger_price}, hủy xác nhận SHORT.")
                                self.pending_side = None
                            elif elapsed_confirm >= CONFIRMATION_TIME:
                                self.open_position('sell', current_price, sell_diff)
                                self.pending_side = None

            # Logic Đóng lệnh (Dựa trên xu hướng 3p)
            elif self.current_position == 'buy':
                if current_price <= price_trend_ago:
                    self.close_position(current_price, f"Giá đảo chiều ({current_price:,.1f} <= {price_trend_ago:,.1f})")
            elif self.current_position == 'sell':
                if current_price >= price_trend_ago:
                    self.close_position(current_price, f"Giá đảo chiều ({current_price:,.1f} >= {price_trend_ago:,.1f})")

            # Báo cáo 10p
            if current_time - self.last_status_time >= STATUS_REPORT_INTERVAL:
                self.send_periodic_status(current_price, price_trend_ago, buy_diff, sell_diff)
                self.last_status_time = current_time

            # Log console (thêm thông báo đang chờ xác nhận nếu có)
            pending_str = f" | Đang chờ {self.pending_side.upper()} ({int(current_time - self.trigger_time)}s)" if self.pending_side else ""
            print(f"[{SYMBOL}] {current_price:,.1f} | B:{buy_diff*100:.1f}% | S:{sell_diff*100:.1f}%{pending_str}")
            time.sleep(CHECK_INTERVAL)

    def send_periodic_status(self, price, price_3p, buy_diff, sell_diff):
        trend = "TĂNG 📈" if price > price_3p else "GIẢM 📉"
        diff_str = f"MUA +{buy_diff*100:.1f}%" if buy_diff > sell_diff else f"BÁN +{sell_diff*100:.1f}%"
        msg = (
            f"📊 *GIÁM SÁT 10 PHÚT*\n"
            f"💰 Giá: `{price:,.2f}`\n"
            f"🔄 Trend 3p: `{trend}`\n"
            f"⚖️ Vol 30p: `{diff_str}`\n"
            f"📍 Vị thế: `{'TRỐNG' if self.current_position is None else self.current_position.upper()}`\n"
            f"🏦 Số dư: `${self.balance:,.2f}`"
        )
        send_telegram(msg)

    def open_position(self, side, price, diff):
        self.current_position = side
        self.entry_price = price
        self.current_trade_amount = min(self.balance, DEFAULT_TRADE_AMOUNT)
        self.amount_coin = (self.current_trade_amount * LEVERAGE) / price
        emoji = "🟢" if side == 'buy' else "🔴"
        msg = (
            f"{emoji} *VÀO LỆNH {side.upper()}*\n"
            f"💰 Giá vào: `{price:,.2f}`\n"
            f"✅ Đã xác nhận giữ giá trong 60s\n"
            f"📊 Vol 30p: `+{diff*100:.1f}%` 🔥\n"
            f"💵 Quy mô: `${self.current_trade_amount:,.2f}`"
        )
        send_telegram(msg)

    def close_position(self, price, reason):
        pnl = (price - self.entry_price) * self.amount_coin if self.current_position == 'buy' else (self.entry_price - price) * self.amount_coin
        self.balance += pnl
        self.last_close_time = time.time()
        msg = (
            f"⚠️ *ĐÓNG LỆNH*\n"
            f"📝 Lý do: {reason}\n"
            f"🏁 PnL: `{pnl:,.2f}$`\n"
            f"🏦 Số dư: `${self.balance:,.2f}`\n"
            f"⏳ Nghỉ 3p."
        )
        send_telegram(msg)
        self.current_position = None

if __name__ == "__main__":
    bot_trading = TradingBot()
    try:
        bot_trading.run()
    except KeyboardInterrupt:
        send_telegram("🛑 *Bot đã dừng.*")
