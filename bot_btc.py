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
CHECK_INTERVAL = 1   # Giây (Đã giảm xuống 1 giây để quét liên tục)
TRADES_LIMIT = 100   # Số lượng giao dịch gần nhất để tính khối lượng

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
        self.current_trade_amount = 0 # Số tiền thực tế dùng cho lệnh hiện tại

    def get_market_data(self):
        try:
            ticker = exchange.fetch_ticker(SYMBOL)
            price = ticker['last']
            
            trades = exchange.fetch_trades(SYMBOL, limit=TRADES_LIMIT)
            buy_volume = sum(t['amount'] for t in trades if t['side'] == 'buy')
            sell_volume = sum(t['amount'] for t in trades if t['side'] == 'sell')
            
            return price, buy_volume, sell_volume
        except Exception as e:
            print(f"Lỗi lấy dữ liệu thị trường: {e}")
            return None, 0, 0

    def run(self):
        send_telegram(f"🚀 *Bot BTC/USDT Demo (Quét nhanh 1s) đã khởi động!*\n- Vốn: `${self.balance:,.2f}`\n- Đòn bẩy: `{LEVERAGE}x`\n- Lệnh tối đa: `${DEFAULT_TRADE_AMOUNT:,.2f}`")
        
        while True:
            price, buy_vol, sell_vol = self.get_market_data()
            
            if price is None:
                time.sleep(CHECK_INTERVAL)
                continue

            signal = 'buy' if buy_vol > sell_vol else 'sell'
            
            if self.current_position is None:
                if self.balance > 0:
                    self.open_position(signal, price, buy_vol, sell_vol)
                else:
                    print("Tài khoản đã hết số dư để giao dịch.")
            elif self.current_position == 'buy' and signal == 'sell':
                self.close_position(price)
                if self.balance > 0:
                    self.open_position('sell', price, buy_vol, sell_vol)
            elif self.current_position == 'sell' and signal == 'buy':
                self.close_position(price)
                if self.balance > 0:
                    self.open_position('buy', price, buy_vol, sell_vol)
            
            # Log console để bạn theo dõi trên Railway
            print(f"[{SYMBOL}] Giá: {price:,.2f} | B-Vol: {buy_vol:,.4f} | S-Vol: {sell_vol:,.4f} | Pos: {self.current_position}")
            
            time.sleep(CHECK_INTERVAL)

    def open_position(self, side, price, b_vol, s_vol):
        self.current_position = side
        self.entry_price = price
        self.current_trade_amount = min(self.balance, DEFAULT_TRADE_AMOUNT)
        self.amount_coin = (self.current_trade_amount * LEVERAGE) / price
        
        emoji = "🟢" if side == 'buy' else "🔴"
        action = "LONG (MUA)" if side == 'buy' else "SHORT (BÁN)"
        msg = (
            f"{emoji} *VÀO LỆNH {action}*\n"
            f"💰 Giá vào: `{price:,.2f}`\n"
            f"📊 Khối lượng Mua: `{b_vol:,.4f}`\n"
            f"📊 Khối lượng Bán: `{s_vol:,.4f}`\n"
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
        self.current_trade_amount = 0

if __name__ == "__main__":
    bot_trading = TradingBot()
    try:
        bot_trading.run()
    except KeyboardInterrupt:
        send_telegram("🛑 *Bot đã dừng.*")
