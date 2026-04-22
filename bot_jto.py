import ccxt
import time
import os
import telebot
from dotenv import load_dotenv

# Load biến môi trường từ file .env (nếu có) hoặc từ Railway
load_dotenv()

# --- CẤU HÌNH ---
SYMBOL = 'JTO/USDT'  # Cặp giao dịch
LEVERAGE = 5         # Đòn bẩy
TRADE_AMOUNT = 10    # Số tiền mỗi lệnh (USD)
INITIAL_BALANCE = 100 # Vốn demo ban đầu
CHECK_INTERVAL = 10  # Giây (Thời gian mỗi lần kiểm tra giá và khối lượng)

# --- THÔNG TIN TELEGRAM ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- KHỞI TẠO EXCHANGE (Sử dụng OKX hoặc Binance công khai để lấy dữ liệu) ---
# Ở đây dùng CCXT để lấy dữ liệu thị trường
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
        self.current_position = None  # 'long', 'short' hoặc None
        self.entry_price = 0
        self.amount_coin = 0
        self.total_pnl = 0

    def get_market_data(self):
        """Lấy giá hiện tại và tính toán khối lượng mua/bán từ 100 giao dịch gần nhất."""
        try:
            ticker = exchange.fetch_ticker(SYMBOL)
            price = ticker['last']
            
            trades = exchange.fetch_trades(SYMBOL, limit=100)
            buy_volume = sum(t['amount'] for t in trades if t['side'] == 'buy')
            sell_volume = sum(t['amount'] for t in trades if t['side'] == 'sell')
            
            return price, buy_volume, sell_volume
        except Exception as e:
            print(f"Lỗi lấy dữ liệu thị trường: {e}")
            return None, 0, 0

    def run(self):
        send_telegram(f"🚀 *Bot JTO/USDT Demo đã khởi động!*\n- Vốn: ${self.balance}\n- Đòn bẩy: {LEVERAGE}x\n- Mỗi lệnh: ${TRADE_AMOUNT}")
        
        while True:
            price, buy_vol, sell_vol = self.get_market_data()
            
            if price is None:
                time.sleep(CHECK_INTERVAL)
                continue

            # Xác định tín hiệu dựa trên khối lượng
            signal = 'buy' if buy_vol > sell_vol else 'sell'
            
            # --- LOGIC GIAO DỊCH ---
            
            # 1. Nếu chưa có lệnh nào
            if self.current_position is None:
                self.open_position(signal, price, buy_vol, sell_vol)
            
            # 2. Nếu đang LONG mà tín hiệu đổi sang SELL (Khối lượng bán cao hơn)
            elif self.current_position == 'long' and signal == 'sell':
                self.close_position(price)
                self.open_position('sell', price, buy_vol, sell_vol)
                
            # 3. Nếu đang SHORT mà tín hiệu đổi sang BUY (Khối lượng mua cao hơn)
            elif self.current_position == 'short' and signal == 'buy':
                self.close_position(price)
                self.open_position('buy', price, buy_vol, sell_vol)
            
            # Log trạng thái nhẹ nhàng
            print(f"[{SYMBOL}] Giá: {price} | Buy Vol: {buy_vol:.2f} | Sell Vol: {sell_vol:.2f} | Pos: {self.current_position}")
            
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
            f"💰 Giá vào: `{price}`\n"
            f"📊 Khối lượng Mua: `{b_vol:.2f}` | Bán: `{s_vol:.2f}`\n"
            f"💵 Quy mô: ${TRADE_AMOUNT} (x{LEVERAGE})"
        )
        send_telegram(msg)

    def close_position(self, price):
        # Tính PnL
        if self.current_position == 'long':
            pnl = (price - self.entry_price) * self.amount_coin
        else:
            pnl = (self.entry_price - price) * self.amount_coin
            
        self.balance += pnl
        self.total_pnl += pnl
        
        status = "LÃI" if pnl > 0 else "LỖ"
        emoji = "✅" if pnl > 0 else "❌"
        
        msg = (
            f"{emoji} *ĐÓNG LỆNH {self.current_position.upper()}*\n"
            f"🏁 Giá đóng: `{price}`\n"
            f"💵 PnL: `{pnl:.2f}$` ({status})\n"
            f"🏦 Số dư Demo: `{self.balance:.2f}$`"
        )
        send_telegram(msg)
        self.current_position = None

if __name__ == "__main__":
    bot_trading = TradingBot()
    try:
        bot_trading.run()
    except KeyboardInterrupt:
        send_telegram("🛑 *Bot đã dừng.*")
