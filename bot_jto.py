import ccxt
import time
import os
import telebot
from dotenv import load_dotenv

# Load biến môi trường từ file .env (nếu có) hoặc từ Railway
load_dotenv()

# --- CẤU HÌNH ---
SYMBOL = 'JTO/USDT'  # Cặp giao dịch
LEVERAGE = 10        # Đòn bẩy
TRADE_AMOUNT = 100   # Số tiền mỗi lệnh (USD)
INITIAL_BALANCE = 100 # Vốn demo ban đầu (Đã đổi về 100$ theo yêu cầu)
CHECK_INTERVAL = 10  # Giây
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
        self.total_pnl = 0

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
        send_telegram(f"🚀 *Bot JTO/USDT Demo đã cập nhật!*\n- Vốn ban đầu: `${INITIAL_BALANCE:,.2f}`\n- Đòn bẩy: `{LEVERAGE}x`\n- Mỗi lệnh: `${TRADE_AMOUNT:,.2f}`\n- Phân tích: `{TRADES_LIMIT}` giao dịch gần nhất")
        
        while True:
            price, buy_vol, sell_vol = self.get_market_data()
            
            if price is None:
                time.sleep(CHECK_INTERVAL)
                continue

            signal = 'buy' if buy_vol > sell_vol else 'sell'
            
            if self.current_position is None:
                self.open_position(signal, price, buy_vol, sell_vol)
            elif self.current_position == 'buy' and signal == 'sell':
                self.close_position(price)
                self.open_position('sell', price, buy_vol, sell_vol)
            elif self.current_position == 'sell' and signal == 'buy':
                self.close_position(price)
                self.open_position('buy', price, buy_vol, sell_vol)
            
            print(f"[{SYMBOL}] Giá: {price:,.4f} | B-Vol: {buy_vol:,.2f} | S-Vol: {sell_vol:,.2f} | Pos: {self.current_position}")
            time.sleep(CHECK_INTERVAL)

    def open_position(self, side, price, b_vol, s_vol):
        self.current_position = side
        self.entry_price = price
        # Giả lập số lượng coin mua được với đòn bẩy
        self.amount_coin = (TRADE_AMOUNT * LEVERAGE) / price
        
        emoji = "🟢" if side == 'buy' else "🔴"
        action = "LONG (MUA)" if side == 'buy' else "SHORT (BÁN)"
        msg = (
            f"{emoji} *VÀO LỆNH {action}*\n"
            f"💰 Giá vào: `{price:,.4f}`\n"
            f"📊 Khối lượng Mua: `{b_vol:,.2f}`\n"
            f"📊 Khối lượng Bán: `{s_vol:,.2f}`\n"
            f"💵 Quy mô: `${TRADE_AMOUNT:,.2f}` (x{LEVERAGE})"
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
            f"🏁 Giá vào: `{self.entry_price:,.4f}`\n"
            f"🏁 Giá đóng: `{price:,.4f}`\n"
            f"💵 PnL lệnh này: `{pnl:,.2f}$` ({status})\n"
            f"--------------------------\n"
            f"🏦 *TỔNG KẾT TÀI KHOẢN:*\n"
            f"💰 Vốn gốc: `${INITIAL_BALANCE:,.2f}`\n"
            f"💵 Số dư hiện tại: `${self.balance:,.2f}`\n"
            f"📈 Tổng Lời/Lỗ: `{self.balance - INITIAL_BALANCE:,.2f}$`"
        )
        send_telegram(msg)
        self.current_position = None

if __name__ == "__main__":
    bot_trading = TradingBot()
    try:
        bot_trading.run()
    except KeyboardInterrupt:
        send_telegram("🛑 *Bot đã dừng.*")
