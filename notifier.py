import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def send_telegram(title: str, content: str, bot_token: str, chat_id: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        message = f"🚀 *{title}*\n\n{content}"

        data = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }).encode('utf-8')

        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.getcode() == 200
    except Exception as e:
        print(f"❌ Telegram 推送失败: {e}")
        return False

def push_notification(title: str, content: str):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")

    if not token or not chat_id:
        return

    send_telegram(title, content, token, chat_id)

class TradingNotifier:
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self.last_hourly_push = 0

    def _get_status_line(self, price, pos, entry, pnl, pnl_pct, ts, mode=''):
        mode_str = f"🔧 Mode: {mode}\n" if mode else ""
        return (f"💰 Price: {price:.2f}\n"
                f"📊 Pos: {pos}\n"
                f"📍 Entry: {entry:.2f}\n"
                f"📈 PnL: {pnl:+.2f} ({pnl_pct:+.2f}%)\n"
                f"🛡️ TS: {ts:.2f}\n"
                f"{mode_str}")

    def push_startup(self, status_data: dict):
        status_line = self._get_status_line(**status_data)
        content = f"✅ *机器人启动运行中*\n策略: {self.strategy_name}\n\n{status_line}"
        push_notification("系统启动", content)

    def push_entry(self, side, price, amount, balance_info, mode=''):
        mode_str = f"🔧 Mode: {mode}" if mode else ""
        content = (f"🚀 *发现进场信号并成交*\n"
                   f"方向: {side}\n"
                   f"价格: {price:.2f}\n"
                   f"数量: {amount:.4f}\n"
                   f"----------\n"
                   f"💰 账户余额: {balance_info.get('usdt_balance', 0):.2f}\n"
                   f"📊 持仓市值: {balance_info.get('position_value', 0):.2f}\n"
                   f"💎 总资金: {balance_info.get('total_equity', 0):.2f}\n"
                   f"----------\n"
                   f"策略: {self.strategy_name}\n"
                   f"{mode_str}")
        push_notification("开仓通知", content)

    def push_exit(self, side, price, pnl, pnl_pct, reason, balance_info, mode=''):
        mode_str = f"🔧 Mode: {mode}" if mode else ""
        content = (f"🏁 *平仓订单已成交*\n"
                   f"方向: {side}\n"
                   f"价格: {price:.2f}\n"
                   f"原因: {reason}\n"
                   f"----------\n"
                   f"💰 账户余额: {balance_info.get('usdt_balance', 0):.2f}\n"
                   f"📊 持仓市值: {balance_info.get('position_value', 0):.2f}\n"
                   f"💎 总资金: {balance_info.get('total_equity', 0):.2f}\n"
                   f"✨ 战绩: {pnl:+.2f} ({pnl_pct:+.2f}%)\n"
                   f"----------\n"
                   f"策略: {self.strategy_name}\n"
                   f"{mode_str}")
        push_notification("平仓通知", content)

    def check_hourly_push(self, status_data: dict):
        now = time.time()
        if now - self.last_hourly_push >= 10800:
            status_line = self._get_status_line(**status_data)
            content = f"🕒 *3小时状态报送*\n策略: {self.strategy_name}\n\n{status_line}"
            push_notification("巡检状态", content)
            self.last_hourly_push = now
            return True
        return False

    def push_error(self, error_msg: str, action: str = "交易执行"):
        content = (f"❌ *{action}失败*\n"
                   f"原因: {error_msg}\n"
                   f"策略: {self.strategy_name}\n"
                   f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        push_notification("交易预警", content)