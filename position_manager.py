import json
from datetime import datetime
from pathlib import Path

class PositionManager:
    def __init__(self, symbol, data_dir='data'):
        self.symbol = symbol
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.position_file = self.data_dir / f'position_{symbol.replace("/", "_")}.json'

        self.position = {
            'has_position': False,
            'position_type': None,
            'entry_price': 0,
            'entry_time': None,
            'entry_idx': 0,
            'entry_peak': 0,
            'position_size': 0,
            'unrealized_pnl': 0,
            'stop_loss': 0,
            'take_profit': 0,
            'trailing_stop': 0,
        }

        self.equity = {
            'initial': 10000,
            'current': 10000,
            'peak': 10000,
            'drawdown': 0,
            'daily_pnl': 0,
            'daily_trades': 0,
        }

        self.load()

    def load(self):
        if self.position_file.exists():
            with open(self.position_file, 'r') as f:
                data = json.load(f)
                self.position = data.get('position', self.position)
                self.equity = data.get('equity', self.equity)

    def save(self):
        data = {
            'position': self.position,
            'equity': self.equity,
            'last_updated': datetime.now().isoformat()
        }
        with open(self.position_file, 'w') as f:
            json.dump(data, f, indent=2)

    def open_position(self, position_type, entry_price, entry_time, entry_idx,
                     position_size, stop_loss, take_profit, trailing_stop):
        self.position = {
            'has_position': True,
            'position_type': position_type,
            'entry_price': entry_price,
            'entry_time': entry_time.isoformat() if isinstance(entry_time, datetime) else entry_time,
            'entry_idx': entry_idx,
            'entry_peak': entry_price,
            'position_size': position_size,
            'unrealized_pnl': 0,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'trailing_stop': trailing_stop,
        }
        self.save()

    def close_position(self, exit_price, exit_time, pnl, exit_reason):
        self.equity['current'] += pnl
        if self.equity['current'] > self.equity['peak']:
            self.equity['peak'] = self.equity['current']
        self.equity['drawdown'] = (self.equity['peak'] - self.equity['current']) / self.equity['peak']
        self.equity['daily_pnl'] += pnl
        self.equity['daily_trades'] += 1

        trade_record = {
            'entry_time': self.position['entry_time'],
            'exit_time': exit_time.isoformat() if isinstance(exit_time, datetime) else exit_time,
            'entry_price': self.position['entry_price'],
            'exit_price': exit_price,
            'position_type': self.position['position_type'],
            'position_size': self.position['position_size'],
            'pnl': pnl,
            'return': pnl / self.equity['initial'],
            'exit_reason': exit_reason,
            'equity_after': self.equity['current'],
            'timestamp': datetime.now().isoformat()
        }

        self.position = {
            'has_position': False,
            'position_type': None,
            'entry_price': 0,
            'entry_time': None,
            'entry_idx': 0,
            'entry_peak': 0,
            'position_size': 0,
            'unrealized_pnl': 0,
            'stop_loss': 0,
            'take_profit': 0,
            'trailing_stop': 0,
        }
        self.save()
        return trade_record

    def update_unrealized_pnl(self, current_price):
        if self.position['has_position']:
            if self.position['position_type'] == 'LONG':
                self.position['unrealized_pnl'] = (
                    (current_price - self.position['entry_price']) /
                    self.position['entry_price'] * self.position['position_size']
                )
            return self.position['unrealized_pnl']
        return 0

    def update_peak(self):
        if self.equity['current'] > self.equity['peak']:
            self.equity['peak'] = self.equity['current']
        self.equity['drawdown'] = (self.equity['peak'] - self.equity['current']) / self.equity['peak']

    def check_risk_limits(self, max_daily_loss=0.01, max_drawdown_stop=0.15):
        daily_loss_ratio = abs(self.equity['daily_pnl']) / self.equity['initial']
        if self.equity['daily_pnl'] < 0 and daily_loss_ratio > max_daily_loss:
            return False, f"Daily loss limit exceeded: {daily_loss_ratio:.2%} > {max_daily_loss:.2%}"

        if self.equity['drawdown'] > max_drawdown_stop:
            return False, f"Max drawdown limit exceeded: {self.equity['drawdown']:.2%} > {max_drawdown_stop:.2%}"

        return True, "Risk check passed"

    def reset_daily(self):
        self.equity['daily_pnl'] = 0
        self.equity['daily_trades'] = 0