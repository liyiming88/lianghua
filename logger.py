import logging
from datetime import datetime
from pathlib import Path

class TradeFileHandler(logging.Handler):
    def __init__(self, log_file):
        super().__init__()
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record):
        if 'TRADE' in record.getMessage() or 'SIGNAL' in record.getMessage():
            with open(self.log_file, 'a') as f:
                f.write(self.format(record) + '\n')


class TradingLogger:
    def __init__(self, name='trading_bot', log_dir='logs'):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.trade_logger = logging.getLogger(f'{name}_trades')
        self.trade_logger.setLevel(logging.INFO)
        self.trade_logger.handlers = []

        trade_file = self.log_dir / f'trades_{datetime.now().strftime("%Y%m%d")}.log'
        trade_handler = TradeFileHandler(trade_file)
        trade_handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self.trade_logger.addHandler(trade_handler)

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        self.logger.handlers = []

        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def info(self, msg):
        self.logger.info(msg)

    def debug(self, msg):
        self.logger.debug(msg)

    def warning(self, msg):
        self.logger.warning(msg)

    def error(self, msg):
        self.logger.error(msg)

    def critical(self, msg):
        self.logger.critical(msg)

    def log_signal(self, signal_type, price, indicators):
        trade_msg = f"SIGNAL | {signal_type} | Price: {price:.4f}"
        self.logger.info(trade_msg)
        self.trade_logger.info(trade_msg)

    def log_order(self, order_id, order_type, side, price, size, status):
        self.logger.info(f"ORDER | {order_id} | {order_type} {side} | Price: {price:.4f} | Size: {size} | Status: {status}")

    def log_trade(self, entry_price, exit_price, pnl, return_pct, exit_reason):
        if exit_price == 0:
            trade_msg = f"OPEN | Entry: {entry_price:.4f} | Reason: {exit_reason}"
        else:
            trade_msg = f"CLOSE | Entry: {entry_price:.4f} | Exit: {exit_price:.4f} | PnL: {pnl:.2f} | Return: {return_pct:.2%} | Reason: {exit_reason}"
        self.logger.info(trade_msg)
        self.trade_logger.info(trade_msg)

    def log_position(self, has_position, position_type, entry_price, current_price, unrealized_pnl):
        pass

    def log_balance(self, balance_info, current_price):
        self.logger.info(f"BALANCE | Price: {current_price:.2f} | USDT: {balance_info['usdt_balance']:.2f} | Pos: {balance_info['position_value']:.2f} | Total: {balance_info['total_equity']:.2f} | Cost: {balance_info['total_cost']:.2f}")