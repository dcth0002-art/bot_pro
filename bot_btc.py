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
RESET_INTERVAL = 3600 
VOL_DIFF_THRESHOLD = 0.50 # Chênh lệch 50% để VÀO LỆNH
STATUS_REPORT_INTERVAL = 600 # 600 giây = 10 phút báo cáo 1 lần

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
        self.last_status_time = time.time()
        self.is_warmed_up = False
        
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

            ticker = exchange.fetch_ticker(SYMBOL)
            current_price = ticker['last']
            self.price_history.append(current_price)
            
            return current_price
        except Exception as e:
            print(f"Lỗi cập nhật dữ liệu: {e}")
            return None

    def send_periodic_status(self, price, price_3p, buy_diff, sell_diff):
        """Gửi báo cáo trạng thái thị trường mỗi 10 phút."""
        trend = "TĂNG 📈" if price > price_3p else "GIẢM 📉"
        diff_val = buy_diff if buy_diff > sell_diff else sell_diff
        side_str = "MUA" if buy_diff > sell_diff else "BÁN"
        
        status_msg = (
            f"📊 *BÁO CÁO ĐỊNH KỲ (10 PHÚT)*\n"
            f"💰 Giá hiện tại: `{price:,.2f}`\n"
            f"🔄 Xu hướng 3p: `{trend}` (So với: {price_3p:,.2f})\n"
            f"⚖️ Chênh lệch Vol: `{side_str} +{diff_val*100:.1f}%`\n"
            f"📍 Vị thế: `{'Đang trống' if self.current_position is None else self.current_position.upper()}`\n"
            f"🏦 Số dư: `${self.balance:,.2f}`"
        )
        send_telegram(status_msg)

    def run(self):
        send_telegram(f"🚀 *Bot BTC/USDT (Cập nhật chiến thuật) đã khởi động!*\n- Vào lệnh: Chênh lệch Vol > 50% & Giá đúng hướng 3p\n- Đóng lệnh: Khi giá đảo chiều 3p (Không quan tâm Vol)")
        
        while True:
            current_price = self.update_data()
            if current_price is None:
                time.sleep(CHECK_INTERVAL)
                continue

            current_time = time.time()
            elapsed_time = current_time - self.start_time
            
            if not self.is_warmed_up:
                if elapsed_time >= WARMUP_PERIOD:
                    self.is_warmed_up = True
                    send_telegram("✅ *Tích lũy xong!* Bắt đầu quét tín hiệu.")
                else:
                    time.sleep(CHECK_INTERVAL)
                    continue

            # Lấy giá 3 phút trước
            price_trend_ago = self.price_history[-180] if len(self.price_history) >= 180 else self.price_history[0]
            
            # Tính % chênh lệch
            buy_diff = (self.total_buy_vol - self.total_sell_vol) / self.total_sell_vol if self.total_sell_vol > 0 else 1.0
            sell_diff = (self.total_sell_vol - self.total_buy_vol) / self.total_buy_vol if self.total_buy_vol > 0 else 1.0

            # Gửi báo cáo định kỳ mỗi 10 phút
            if current_time - self.last_status_time >= STATUS_REPORT_INTERVAL:
                self.send_periodic_status(current_price, price_trend_ago, buy_diff, sell_diff)
                self.last_status_time = current_time

            vol_buy_strong = buy_diff > VOL_DIFF_THRESHOLD
            vol_sell_strong = sell_diff > VOL_DIFF_THRESHOLD
            price_uptrend = current_price > price_trend_ago
            price_downtrend = current_price < price_trend_ago

            # LOGIC GIAO DỊCH
            if self.current_position is None:
                # Điều kiện vào lệnh: Vol chênh > 50% VÀ Giá đi đúng hướng
                if vol_buy_strong and price_uptrend:
                    if self.balance > 0: self.open_position('buy', current_price, buy_diff)
                elif vol_sell_strong and price_downtrend:
                    if self.balance > 0: self.open_position('sell', current_price, sell_diff)
            
            elif self.current_position == 'buy':
                # Đóng lệnh LONG: Chỉ đóng khi giá đảo chiều (không còn cao hơn 3p trước)
                if not price_uptrend:
                    reason = f"Giá đảo chiều/đi ngang ({current_price:,.2f} <= {price_trend_ago:,.2f})"
                    self.close_position(current_price, reason)
            
            elif self.current_position == 'sell':
                # Đóng lệnh SHORT: Chỉ đóng khi giá đảo chiều (không còn thấp hơn 3p trước)
                if not price_downtrend:
                    reason = f"Giá đảo chiều/đi ngang ({current_price:,.2f} >= {price_trend_ago:,.2f})"
                    self.close_position(current_price, reason)

            print(f"[{SYMBOL}] {current_price:,.2f} | B:{buy_diff*100:.1f}% | S:{sell_diff*100:.1f}% | 3p:{price_trend_ago:,.2f}")
            time.sleep(CHECK_INTERVAL)

    def open_position(self, side, price, diff):
        self.current_position = side
        self.entry_price = price
        self.current_trade_amount = min(self.balance, DEFAULT_TRADE_AMOUNT)
        self.amount_coin = (self.current_trade_amount * LEVERAGE) / price
        
        emoji = "🟢" if side == 'buy' else "🔴"
        action = "LONG" if side == 'buy' else "SHORT"
        
        msg = (
            f"{emoji} *VÀO LỆNH {action}*\n"
            f"💰 Giá vào: `{price:,.2f}`\n"
            f"📊 Chênh lệch Vol: `+{diff*100:.1f}%` 🔥\n"
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
            f"🏁 Giá vào: `{self.entry_price:,.2f}`\n"
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
