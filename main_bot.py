import ccxt
import yaml
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import time
import json
import sys
import os

sys.path.append(str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from position_manager import PositionManager
from logger import TradingLogger
from notifier import TradingNotifier

class TrendGuardStrategyV14:
    def __init__(self, config):
        p = config['parameters']
        self.price_pos_period = p['price_pos_period']
        self.price_pos_entry = p['price_pos_entry']
        self.price_pos_exit = p['price_pos_exit']
        self.price_pos_bear_filter = p['price_pos_bear_filter']
        self.vol_period_fast = p['vol_period_fast']
        self.vol_period_slow = p['vol_period_slow']
        self.vol_ratio_threshold = p['vol_ratio_threshold']
        self.momentum_period = p['momentum_period']
        self.momentum_threshold = p['momentum_threshold']
        self.momentum_exit_threshold = p['momentum_exit_threshold']
        self.atr_period = p['atr_period']
        self.atr_ma_period = p['atr_ma_period']
        self.atr_threshold = p['atr_threshold']
        self.market_regime_threshold = p['market_regime_threshold']
        self.stop_loss = p['stop_loss']
        self.take_profit = p['take_profit']
        self.trailing_stop = p['trailing_stop']
        self.max_holding_periods = p['max_holding_periods']

    def calculate_indicators(self, df):
        df = df.copy()
        df['returns'] = df['close'].pct_change()

        df['volatility_fast'] = df['returns'].rolling(self.vol_period_fast).std()
        df['volatility_slow'] = df['returns'].rolling(self.vol_period_slow).std()
        df['vol_ratio'] = df['volatility_fast'] / (df['volatility_slow'] + 1e-10)

        rolling_max = df['close'].rolling(self.price_pos_period).max()
        rolling_min = df['close'].rolling(self.price_pos_period).min()
        df['price_position'] = (df['close'] - rolling_min) / (rolling_max - rolling_min + 1e-10)

        df['momentum'] = df['close'] / df['close'].shift(self.momentum_period) - 1

        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=self.atr_period).mean()
        df['atr_ma'] = df['atr'].rolling(window=self.atr_ma_period).mean()
        df['atr_ratio'] = df['atr'] / (df['atr_ma'] + 1e-10)

        df['market_regime'] = df['price_position'] * df['vol_ratio']

        return df

    def generate_signals(self, df):
        df = self.calculate_indicators(df)
        df = df.dropna().reset_index(drop=True)

        market_filter = df['market_regime'] > self.market_regime_threshold

        df['long_signal'] = (
            (df['price_position'] > self.price_pos_entry) &
            (df['vol_ratio'] > self.vol_ratio_threshold) &
            (df['momentum'] > self.momentum_threshold) &
            (df['atr_ratio'] > self.atr_threshold) &
            market_filter
        )

        df['exit_long'] = (
            (df['price_position'] < self.price_pos_exit) |
            (df['momentum'] < self.momentum_exit_threshold)
        )

        return df


class SimulatedTrader:
    def __init__(self, config):
        self.config = config
        sim_config = config.get('simulation', {})
        self.enabled = sim_config.get('enabled', True)
        self.initial_balance = sim_config.get('initial_balance', 1000)
        self.fee_rate = sim_config.get('fee_rate', 0.0005)
        self.slippage = sim_config.get('slippage', 0.0005)

        self.balance = self.initial_balance
        self.position = {
            'has_position': False,
            'position_type': None,
            'entry_price': 0,
            'entry_size': 0,
            'entry_time': None,
            'entry_idx': 0,
            'entry_peak': 0,
            'position_cost': 0,
        }

        self.trades = []
        self.equity_curve = []
        self.daily_pnl = 0
        self.total_cost = 0

        data_file = Path('data/simulated_trades.json')
        if data_file.exists():
            with open(data_file, 'r') as f:
                data = json.load(f)
                self.balance = data.get('balance', self.initial_balance)
                self.position = data.get('position', self.position)
                self.trades = data.get('trades', [])
                self.total_cost = data.get('total_cost', 0)

    def save_state(self):
        data = {
            'balance': self.balance,
            'position': self.position,
            'trades': self.trades[-100:],
            'total_cost': self.total_cost,
            'last_updated': datetime.now().isoformat()
        }
        Path('data').mkdir(parents=True, exist_ok=True)
        with open('data/simulated_trades.json', 'w') as f:
            json.dump(data, f, indent=2)

    def open_position(self, position_type, price, size, idx, time):
        entry_price = price * (1 + self.slippage)
        open_cost = self.balance * self.fee_rate
        self.balance -= open_cost
        self.total_cost += open_cost

        position_cost = size * entry_price
        self.balance -= position_cost

        self.position = {
            'has_position': True,
            'position_type': position_type,
            'entry_price': entry_price,
            'entry_size': size,
            'entry_time': time.isoformat() if isinstance(time, datetime) else time,
            'entry_idx': idx,
            'entry_peak': entry_price,
            'position_cost': position_cost,
        }
        self.save_state()
        return True

    def close_position(self, exit_reason, current_price, idx, time):
        if not self.position['has_position']:
            return None

        exit_price = current_price * (1 - self.slippage)
        position_cost = self.position.get('position_cost', 0)
        size = self.position['entry_size']

        sell_value = size * exit_price
        net_proceeds = sell_value * (1 - self.fee_rate)

        pnl = net_proceeds - position_cost
        self.balance += net_proceeds

        close_cost = sell_value * self.fee_rate
        self.total_cost += close_cost

        trade_record = {
            'entry_time': self.position['entry_time'],
            'exit_time': time.isoformat() if isinstance(time, datetime) else time,
            'entry_price': self.position['entry_price'],
            'exit_price': exit_price,
            'position_type': self.position['position_type'],
            'size': size,
            'return': pnl / position_cost if position_cost > 0 else 0,
            'pnl': pnl,
            'balance_after': self.balance,
            'exit_reason': exit_reason,
        }
        self.trades.append(trade_record)

        self.position = {
            'has_position': False,
            'position_type': None,
            'entry_price': 0,
            'entry_size': 0,
            'entry_time': None,
            'entry_idx': 0,
            'entry_peak': 0,
            'position_cost': 0,
        }
        self.save_state()
        return trade_record

    def get_equity(self, current_price):
        if self.position['has_position']:
            if self.position['position_type'] == 'LONG':
                position_value = self.position['entry_size'] * current_price
                return self.balance + position_value
        return self.balance

    def get_position_value(self, current_price):
        if self.position['has_position']:
            if self.position['position_type'] == 'LONG':
                return self.position['entry_size'] * current_price
        return 0

    def reset_daily(self):
        self.daily_pnl = 0


class OKEXTrader:
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.symbol = self.config['symbol']
        self.timeframe = self.config['timeframe']
        self.leverage = self.config['risk_controls']['leverage']

        sim_config = self.config.get('simulation', {})
        self.simulation_mode = sim_config.get('enabled', True)

        if self.simulation_mode:
            self.simulated_trader = SimulatedTrader(self.config)
            self.logger = TradingLogger(log_dir='logs')
            self.logger.info("=== SIMULATION MODE ENABLED ===")
            self.logger.info(f"Initial Balance: {self.simulated_trader.initial_balance} USDT")
            self.logger.info(f"Fee Rate: {self.simulated_trader.fee_rate*100:.2f}%")
            self.logger.info(f"Slippage: {self.simulated_trader.slippage*100:.2f}%")

            exchange_config = self.config['exchange']
            self.exchange = getattr(ccxt, exchange_config['exchange_id'])({
                'apiKey': os.getenv('ETH_OKX_API_KEY'),
                'secret': os.getenv('ETH_OKX_SECRET_KEY'),
                'password': os.getenv('ETH_OKX_PASSPHRASE'),
                'sandbox': exchange_config.get('sandbox', False),
                'enableRateLimit': False,
            })
        else:
            exchange_config = self.config['exchange']
            self.exchange = getattr(ccxt, exchange_config['exchange_id'])({
                'apiKey': os.getenv('ETH_OKX_API_KEY'),
                'secret': os.getenv('ETH_OKX_SECRET_KEY'),
                'password': os.getenv('ETH_OKX_PASSPHRASE'),
                'sandbox': exchange_config.get('sandbox', False),
            })
            self.exchange.load_markets()

            self.position_manager = PositionManager(self.symbol)
            self.logger = TradingLogger(log_dir='logs')
            self.logger.info("=== LIVE TRADING MODE ===")

        self.strategy = TrendGuardStrategyV14(self.config)
        self.notifier = TradingNotifier(self.config.get('name', 'OKEX_Trading_Bot'))
        self.last_bar_time = None
        self.bar_count = 0
        self.entry_idx = 0

    def fetch_ohlcv(self, limit=200):
        try:
            if self.simulation_mode:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
            else:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            self.logger.error(f"Failed to fetch OHLCV: {e}")
            return None

    def set_leverage(self):
        try:
            market = self.exchange.market(self.symbol)
            if market.get('contract'):
                self.exchange.set_leverage(self.leverage, self.symbol)
                self.logger.info(f"Leverage set to {self.leverage}x")
        except Exception as e:
            self.logger.error(f"Failed to set leverage: {e}")

    def get_position_size(self, current_price):
        if self.simulation_mode:
            balance = self.simulated_trader.balance
            position_value = min(balance * 0.95, balance)
            size = position_value / current_price
            return size
        else:
            balance = self.exchange.fetch_balance()
            usdt_balance = balance['total'].get('USDT', 0)
            if usdt_balance <= 0:
                return 0
            position_value = min(usdt_balance * 0.95, usdt_balance)
            size = position_value / current_price
            return size

    def get_balance_info(self, current_price):
        if self.simulation_mode:
            pos = self.simulated_trader.position
            position_value = 0
            if pos['has_position'] and pos['position_type'] == 'LONG':
                position_value = pos['entry_size'] * current_price
            return {
                'usdt_balance': self.simulated_trader.balance,
                'position_value': position_value,
                'total_equity': self.simulated_trader.balance + position_value,
                'total_cost': self.simulated_trader.total_cost,
            }
        else:
            balance = self.exchange.fetch_balance()
            usdt_balance = balance['total'].get('USDT', 0)
            pos = self.position_manager.position
            position_value = 0
            if pos['has_position'] and pos['position_type'] == 'LONG':
                position_value = pos['position_size'] * current_price
            return {
                'usdt_balance': usdt_balance,
                'position_value': position_value,
                'total_equity': usdt_balance + position_value,
                'total_cost': 0,
            }

    def place_order(self, side, order_type, amount, price=None):
        try:
            if order_type == 'market':
                order = self.exchange.create_order(self.symbol, 'market', side, amount)
            else:
                order = self.exchange.create_order(self.symbol, 'limit', side, amount, price)
            return order
        except Exception as e:
            self.logger.error(f"Failed to place order: {e}")
            return None

    def check_and_close_expired_position(self, current_bar_idx):
        if self.simulation_mode:
            pos = self.simulated_trader.position
        else:
            pos = self.position_manager.position

        if pos['has_position']:
            holding_periods = current_bar_idx - pos['entry_idx']
            if holding_periods >= self.strategy.max_holding_periods:
                self.logger.info(f"Max holding periods reached: {holding_periods}")
                return True
        return False

    def run(self):
        mode_str = "SIMULATION" if self.simulation_mode else "LIVE"
        self.logger.info(f"Starting OKEX Trading Bot | Mode: {mode_str} | Symbol: {self.symbol} | Timeframe: {self.timeframe}")

        if not self.simulation_mode:
            self.set_leverage()

        current_price = self.fetch_ohlcv(limit=1)['close'].iloc[-1] if self.fetch_ohlcv(limit=1) is not None else 0
        balance_info = self.get_balance_info(current_price)
        pos = self.simulated_trader.position if self.simulation_mode else self.position_manager.position

        status_data = {
            'price': current_price,
            'pos': pos.get('position_type', 'NONE'),
            'entry': pos.get('entry_price', 0),
            'pnl': 0,
            'pnl_pct': 0,
            'ts': self.strategy.trailing_stop if pos.get('has_position') else 0,
            'mode': 'SIMULATION' if self.simulation_mode else 'LIVE'
        }
        self.notifier.push_startup(status_data)

        while True:
            try:
                df = self.fetch_ohlcv(limit=200)
                if df is None or len(df) < self.strategy.price_pos_period + 10:
                    self.logger.warning("Insufficient data, waiting...")
                    time.sleep(60)
                    continue

                df = self.strategy.generate_signals(df)
                current_bar = df.iloc[-1]
                prev_bar = df.iloc[-2]
                current_bar_idx = len(df) - 1
                current_price = current_bar['close']

                balance_info = self.get_balance_info(current_price)

                if self.simulation_mode:
                    pos = self.simulated_trader.position
                else:
                    self.position_manager.update_unrealized_pnl(current_price)
                    self.position_manager.update_peak()
                    pos = self.position_manager.position

                    risk_ok, risk_msg = self.position_manager.check_risk_limits(
                        self.config['risk_controls']['max_daily_loss'],
                        self.config['risk_controls']['max_drawdown_stop']
                    )
                    if not risk_ok:
                        self.logger.critical(f"Risk limit triggered: {risk_msg}")
                        if self.position_manager.position['has_position']:
                            self.close_position("RISK_STOP", current_price, current_bar_idx, current_bar['datetime'], balance_info, 'LIVE')
                        time.sleep(60)
                        continue

                if not pos['has_position']:
                    if prev_bar['long_signal'] and self.bar_count > 0:
                        size = self.get_position_size(current_price)
                        if size > 0:
                            if self.simulation_mode:
                                self.simulated_trader.open_position(
                                    'LONG',
                                    current_price,
                                    size,
                                    current_bar_idx,
                                    current_bar['datetime']
                                )
                                self.logger.log_trade(
                                    entry_price=current_price,
                                    exit_price=0,
                                    pnl=0,
                                    return_pct=0,
                                    exit_reason='ENTRY'
                                )
                                self.notifier.push_entry(
                                    'LONG', current_price, size, balance_info,
                                    'SIMULATION' if self.simulation_mode else 'LIVE'
                                )
                            else:
                                order = self.place_order('buy', 'market', size)
                                if order:
                                    self.position_manager.open_position(
                                        'LONG',
                                        current_price,
                                        current_bar['datetime'],
                                        current_bar_idx,
                                        size,
                                        self.strategy.stop_loss,
                                        self.strategy.take_profit,
                                        self.strategy.trailing_stop
                                    )
                                    self.logger.log_trade(
                                        entry_price=current_price,
                                        exit_price=0,
                                        pnl=0,
                                        return_pct=0,
                                        exit_reason='ENTRY'
                                    )
                                    self.notifier.push_entry(
                                        'LONG', current_price, size, balance_info,
                                        'SIMULATION' if self.simulation_mode else 'LIVE'
                                    )
                else:
                    pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                    entry_peak = pos['entry_peak']

                    if current_price > entry_peak:
                        entry_peak = current_price
                        if self.simulation_mode:
                            self.simulated_trader.position['entry_peak'] = entry_peak
                        else:
                            self.position_manager.position['entry_peak'] = entry_peak

                    trailing_trigger = entry_peak * (1 - self.strategy.trailing_stop)

                    should_exit = False
                    exit_reason = 'SIGNAL'

                    if current_bar['exit_long']:
                        should_exit = True
                        exit_reason = 'SIGNAL'
                    if pnl_pct <= -self.strategy.stop_loss:
                        should_exit = True
                        exit_reason = 'STOP_LOSS'
                    if pnl_pct >= self.strategy.take_profit:
                        should_exit = True
                        exit_reason = 'TAKE_PROFIT'
                    if current_price <= trailing_trigger and pnl_pct > 0:
                        should_exit = True
                        exit_reason = 'TRAILING'
                    if self.check_and_close_expired_position(current_bar_idx):
                        should_exit = True
                        exit_reason = 'TIME_EXIT'

                    if should_exit:
                        mode = 'SIMULATION' if self.simulation_mode else 'LIVE'
                        self.close_position(exit_reason, current_price, current_bar_idx, current_bar['datetime'], balance_info, mode)

                if self.simulation_mode:
                    self.simulated_trader.save_state()
                else:
                    self.position_manager.save()

                if prev_bar['long_signal'] and self.bar_count > 0:
                    indicators = {
                        'price_position': current_bar.get('price_position', 0),
                        'vol_ratio': current_bar.get('vol_ratio', 0),
                        'momentum': current_bar.get('momentum', 0),
                        'atr_ratio': current_bar.get('atr_ratio', 0),
                        'market_regime': current_bar.get('market_regime', 0),
                    }
                    self.logger.log_signal('LONG_SIGNAL', current_price, indicators)

                self.logger.log_position(
                    pos['has_position'],
                    pos['position_type'],
                    pos['entry_price'],
                    current_price,
                    0
                )

                self.logger.log_balance(balance_info, current_price)

                status_data = {
                    'price': current_price,
                    'pos': pos.get('position_type', 'NONE'),
                    'entry': pos.get('entry_price', 0),
                    'pnl': (current_price - pos.get('entry_price', 0)) / pos.get('entry_price', 1) if pos.get('has_position') else 0,
                    'pnl_pct': (current_price - pos.get('entry_price', 0)) / pos.get('entry_price', 1) * 100 if pos.get('has_position') else 0,
                    'ts': self.strategy.trailing_stop if pos.get('has_position') else 0,
                    'mode': 'SIMULATION' if self.simulation_mode else 'LIVE'
                }
                self.notifier.check_hourly_push(status_data)

                self.last_bar_time = current_bar['datetime']
                self.bar_count += 1

                time.sleep(30)

            except KeyboardInterrupt:
                self.logger.info("Bot stopped by user")
                if self.simulation_mode:
                    if self.simulated_trader.position['has_position']:
                        mode = 'SIMULATION' if self.simulation_mode else 'LIVE'
                        self.close_position("MANUAL_STOP", current_price, current_bar_idx, current_bar['datetime'], balance_info, mode)
                else:
                    if self.position_manager.position['has_position']:
                        self.close_position("MANUAL_STOP", current_price, None, datetime.now(), balance_info, 'LIVE')
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(60)

    def close_position(self, exit_reason, current_price, idx=None, time=None, balance_info=None, mode=''):
        if balance_info is None:
            balance_info = {'usdt_balance': 0, 'position_value': 0, 'total_equity': 0}

        if self.simulation_mode:
            trade_record = self.simulated_trader.close_position(exit_reason, current_price, idx or 0, time or datetime.now())
            if trade_record:
                self.logger.log_trade(
                    trade_record['entry_price'],
                    trade_record['exit_price'],
                    trade_record['pnl'],
                    trade_record['return'],
                    exit_reason
                )
                self.notifier.push_exit(
                    'LONG', trade_record['exit_price'], trade_record['pnl'],
                    trade_record['return'], exit_reason, balance_info, mode
                )
            return trade_record
        else:
            if current_price is None:
                try:
                    current_price = self.exchange.fetch_ticker(self.symbol)['last']
                except:
                    current_price = self.position_manager.position['entry_price']

            pos = self.position_manager.position
            size = pos['position_size']

            order = self.place_order('sell', 'market', size)
            if order:
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                pnl = self.position_manager.equity['current'] * pnl_pct

                trade_record = self.position_manager.close_position(
                    current_price,
                    datetime.now(),
                    pnl,
                    exit_reason
                )
                self.logger.log_trade(
                    pos['entry_price'],
                    current_price,
                    pnl,
                    pnl_pct,
                    exit_reason
                )
                self.notifier.push_exit(
                    'LONG', current_price, pnl, pnl_pct, exit_reason, balance_info, mode
                )
                return trade_record
            return None


def main():
    bot = OKEXTrader('config.yaml')
    bot.run()


if __name__ == '__main__':
    main()