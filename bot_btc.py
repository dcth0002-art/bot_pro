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
WARMUP_PERIOD = 300 # 300s = 5 phút để tích lũy vol ban đầu
RESET_INTERVAL = 3600 # 1 tiếng

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
        
        self.total_buy_vol = 0.0
        self.total_sell_vol = 0.0
        self.last_trade_id = None
        self.start_time = time.time()
        self.last_reset_time = time.time()
        self.is_warmed_up = False
        
        # Lưu lịch sử giá (giữ 300 giây để có giá từ 5p trước nếu cần, nhưng hiện tại vẫn so với 1p trước)
        self.price_history = deque(maxlen=310) 

    def update_data(self):
        try:
            current_time = time.time()
            if current_time - self.last_reset_time >= RESET_INTERVAL:
                if self.current_position is None:
                    self.total_buy_vol = 0.0
                    self.total_sell_vol = 0.0
                    self.last_reset_time = current_time
                    send_telegram("🔄 *Hệ thống đã reset Volume về 0 (Chu kỳ 1h mới).*")
                else:
                    print("Đã đến lúc reset nhưng đang có lệnh mở, chờ lệnh đóng...")

            # 1. Cập nhật Volume
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
                    if t['side'] == 'buy':
                        self.total_buy_vol += t['amount']
                    else:
                        self.total_sell_vol += t['amount']
                self.last_trade_id = new_trades[-1]['id']

            # 2. Cập nhật Giá
            ticker = exchange.fetch_ticker(SYMBOL)
            current_price = ticker['last']
            self.price_history.append(current_price)
            
            return current_price
        except Exception as e:
            print(f"Lỗi cập nhật dữ liệu: {e}")
            return None

    def run(self):
        send_telegram(f"🚀 *Bot BTC/USDT (Smart Reset) đã khởi động!*\n- Chờ tích lũy ban đầu: `5 phút`\n- Reset Vol: `1 tiếng` (khi rảnh)")
        
        while True:
            current_price = self.update_data()
            if current_price is None:
                time.sleep(CHECK_INTERVAL)
                continue

            elapsed_time = time.time() - self.start_time
            if not self.is_warmed_up:
                # Kiểm tra xem đã qua 5 phút (300 giây) chưa
                if elapsed_time >= WARMUP_PERIOD:
                    self.is_warmed_up = True
                    send_telegram("✅ *Tích lũy xong 5 phút dữ liệu!* Bắt đầu quét tín hiệu giao dịch.")
                else:
                    remaining = WARMUP_PERIOD - int(elapsed_time)
                    if remaining % 60 == 0: # Cập nhật mỗi phút một lần vào console
                        print(f"Đang tích lũy dữ liệu... còn {remaining}s")
                    time.sleep(CHECK_INTERVAL)
                    continue

            # Lấy giá 1 phút trước (60 giây trước) để so sánh xu hướng
            # Vì mỗi giây append 1 lần, giá 1p trước nằm ở vị trí len - 60
            price_1m_ago = self.price_history[-60] if len(self.price_history) >= 60 else self.price_history[0]
            
            vol_buy_dominant = self.total_buy_vol > self.total_sell_vol
            vol_sell_dominant = self.total_sell_vol > self.total_buy_vol
            price_uptrend = current_price > price_1m_ago
            price_downtrend = current_price < price_1m_ago

            if self.current_position is None:
                if vol_buy_dominant and price_uptrend:
                    if self.balance > 0: self.open_position('buy', current_price)
                elif vol_sell_dominant and price_downtrend:
                    if self.balance > 0: self.open_position('sell', current_price)
            
            elif self.current_position == 'buy':
                if not vol_buy_dominant or not price_uptrend:
                    reason = "Vol đảo chiều" if not vol_buy_dominant else "Giá yếu đi"
                    self.close_position(current_price, reason)
            
            elif self.current_position == 'sell':
                if not vol_sell_dominant or not price_downtrend:
                    reason = "Vol đảo chiều" if not vol_sell_dominant else "Giá mạnh lên"
                    self.close_position(current_price, reason)

            print(f"[{SYMBOL}] {current_price:,.2f} | B:{self.total_buy_vol:.3f} S:{self.total_sell_vol:.3f} | 1p:{price_1m_ago:,.2f}")
            time.sleep(CHECK_INTERVAL)

    def open_position(self, side, price):
        self.current_position = side
        self.entry_price = price
        self.current_trade_amount = min(self.balance, DEFAULT_TRADE_AMOUNT)
        self.amount_coin = (self.current_trade_amount * LEVERAGE) / price
        
        emoji = "🟢" if side == 'buy' else "🔴"
        action = "LONG" if side == 'buy' else "SHORT"
        msg = (
            f"{emoji} *VÀO LỆNH {action}*\n"
            f"💰 Giá vào: `{price:,.2f}`\n"
            f"📊 Vol Mua: `{self.total_buy_vol:.4f}` | Bán: `{self.total_sell_vol:.4f}`\n"
            f"💵 Quy mô: `${self.current_trade_amount:,.2f}`"
        )
        send_telegram(msg)

    def close_position(self, price, reason):
        if self.current_position == 'buy':
            pnl = (price - self.entry_price) * self.amount_coin
        else:
            pnl = (self.entry_price - price) * self.amount_coin
            
        self.balance += pnl
        status = "LÃI" if pnl > 0 else "LỖ"
        msg = (
            f"⚠️ *ĐÓNG LỆNH*\n"
            f"📝 Lý do: {reason}\n"
            f"🏁 Giá đóng: `{price:,.2f}`\n"
            f"💵 PnL: `{pnl:,.2f}$` ({status})\n"
            f"🏦 Số dư: `${self.balance:,.2f}`"
        )
        send_telegram(msg)
        self.current_position = None

if __name__ == "__main__":
    bot_trading = TradingBot()
    try:
        bot_trading.run()
    except KeyboardInterrupt:
        send_telegram("🛑 *Bot đã dừng.*")
