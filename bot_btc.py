import ccxt
import time
import os
import telebot
from dotenv import load_dotenv

# Load biến môi trường từ file .env (nếu có) hoặc từ Railway
load_dotenv()

# --- CẤU HÌNH ---
SYMBOL = 'BTC/USDT'  # Cặp giao dịch
LEVERAGE = 10        # Đòn bẩy
DEFAULT_TRADE_AMOUNT = 100 # Số tiền mặc định mỗi lệnh (USD)
INITIAL_BALANCE = 100 # Vốn demo ban đầu
CHECK_INTERVAL = 1   # Giây (Quét liên tục)
WARMUP_PERIOD = 60   # Giây (Thời gian chờ tích lũy khối lượng ban đầu)

# --- THÔNG TIN TELEGRAM ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- KHỞI TẠO EXCHANGE ---
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
        self.current_position = None  # 'buy', 'sell' hoặc None
        self.entry_price = 0
        self.amount_coin = 0
        self.current_trade_amount = 0
        
        # Khối lượng cộng dồn
        self.total_buy_vol = 0.0
        self.total_sell_vol = 0.0
        self.last_trade_id = None
        self.start_time = time.time()
        self.is_warmed_up = False

    def update_cumulative_volume(self):
        """Lấy các giao dịch mới nhất và cộng dồn vào tổng khối lượng."""
        try:
            # Lấy 100 giao dịch mới nhất để đảm bảo không bỏ lỡ trong 1s nghỉ
            trades = exchange.fetch_trades(SYMBOL, limit=100)
            
            new_trades = []
            if self.last_trade_id is None:
                new_trades = trades
            else:
                # Tìm các giao dịch có ID mới hơn ID cuối cùng đã lưu
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
                
            return True
        except Exception as e:
            print(f"Lỗi cập nhật khối lượng: {e}")
            return False

    def run(self):
        send_telegram(f"🚀 *Bot BTC/USDT Tích Lũy Khối Lượng đã khởi động!*\n- Vốn: `${self.balance:,.2f}`\n- Đòn bẩy: `{LEVERAGE}x`\n- Đang chờ {WARMUP_PERIOD}s để tích lũy dữ liệu ban đầu...")
        
        while True:
            # Cập nhật khối lượng cộng dồn liên tục
            success = self.update_cumulative_volume()
            
            try:
                ticker = exchange.fetch_ticker(SYMBOL)
                current_price = ticker['last']
            except:
                time.sleep(CHECK_INTERVAL)
                continue

            elapsed_time = time.time() - self.start_time
            
            # Kiểm tra xem đã qua thời gian khởi động (warmup) chưa
            if not self.is_warmed_up:
                if elapsed_time >= WARMUP_PERIOD:
                    self.is_warmed_up = True
                    send_telegram("✅ *Kết thúc 60s tích lũy!* Bắt đầu giao dịch dựa trên khối lượng cộng dồn.")
                else:
                    print(f"Đang tích lũy... {elapsed_time:.0f}s | B-Vol: {self.total_buy_vol:.4f} | S-Vol: {self.total_sell_vol:.4f}")
                    time.sleep(CHECK_INTERVAL)
                    continue

            # Xác định tín hiệu dựa trên KHỐI LƯỢNG CỘNG DỒN
            signal = 'buy' if self.total_buy_vol > self.total_sell_vol else 'sell'
            
            # Logic giao dịch
            if self.current_position is None:
                if self.balance > 0:
                    self.open_position(signal, current_price)
            elif self.current_position == 'buy' and signal == 'sell':
                self.close_position(current_price)
                if self.balance > 0:
                    self.open_position('sell', current_price)
            elif self.current_position == 'sell' and signal == 'buy':
                self.close_position(current_price)
                if self.balance > 0:
                    self.open_position('buy', current_price)
            
            print(f"[{SYMBOL}] Giá: {current_price:,.2f} | Tổng Mua: {self.total_buy_vol:.4f} | Tổng Bán: {self.total_sell_vol:.4f} | Pos: {self.current_position}")
            
            time.sleep(CHECK_INTERVAL)

    def open_position(self, side, price):
        self.current_position = side
        self.entry_price = price
        self.current_trade_amount = min(self.balance, DEFAULT_TRADE_AMOUNT)
        self.amount_coin = (self.current_trade_amount * LEVERAGE) / price
        
        emoji = "🟢" if side == 'buy' else "🔴"
        action = "LONG (MUA)" if side == 'buy' else "SHORT (BÁN)"
        msg = (
            f"{emoji} *VÀO LỆNH {action}*\n"
            f"💰 Giá vào: `{price:,.2f}`\n"
            f"📊 Tổng Mua tích lũy: `{self.total_buy_vol:.4f}`\n"
            f"📊 Tổng Bán tích lũy: `{self.total_sell_vol:.4f}`\n"
            f"💵 Quy mô: `${self.current_trade_amount:,.2f}` (x{LEVERAGE})"
        )
        send_telegram(msg)

    def close_position(self, price):
        if self.current_position == 'buy':
            pnl = (price - self.entry_price) * self.amount_coin
        else:
            pnl = (self.entry_price - price) * self.amount_coin
            
        self.balance += pnl
        status = "LÃI" if pnl > 0 else "LỖ"
        emoji = "✅" if pnl > 0 else "❌"
        
        msg = (
            f"{emoji} *ĐÓNG LỆNH {self.current_position.upper()}*\n"
            f"🏁 Giá vào: `{self.entry_price:,.2f}`\n"
            f"🏁 Giá đóng: `{price:,.2f}`\n"
            f"💵 PnL lệnh này: `{pnl:,.2f}$` ({status})\n"
            f"--------------------------\n"
            f"🏦 *TỔNG KẾT TÀI KHOẢN:*\n"
            f"💰 Vốn gốc ban đầu: `${INITIAL_BALANCE:,.2f}`\n"
            f"💵 Số dư hiện tại: `${self.balance:,.2f}`\n"
            f"📈 Tổng Lời/Lỗ tích lũy: `{self.balance - INITIAL_BALANCE:,.2f}$`"
        )
        send_telegram(msg)
        self.current_position = None

if __name__ == "__main__":
    bot_trading = TradingBot()
    try:
        bot_trading.run()
    except KeyboardInterrupt:
        send_telegram("🛑 *Bot đã dừng.*")
