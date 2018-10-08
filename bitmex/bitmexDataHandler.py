from qsDataStructure import Orderbook, Tick, Bar, Snapshot
from .bitmexWSMarket2 import bitmexWSMarket2
from .bitmexREST import bitmexREST
from .utils import generate_logger, calculate_td_ts, now
import queue
import threading


class bitmexDataHandler(object):
    def __init__(self, g):
        self.g = g                            # global settings
        self.event_q = None                   # 全局事件队列
        self.market_data_q = queue.Queue()    # MarketData队列（带数据）
        self.td_run = None                    # __run()函数线程
        self.active = False
        self.logger = generate_logger('DataHandler', g.loglevel, g.logfile)  # 日志
        self.symbols = g.symbols               # 订阅的标的  ['XBTUSD', ...]
        self.tick = {}                         # {symbol: Tick}            # 最新的last_price信息
        self.orderbook = {}                    # {symbol: Orderbook}       # 最新的orderbook信息
        self.registered_bar_events = {}   # {'XBTUSD': ['1m', '30s'], ...}
        self.bar = {}                     # {'XBTUSD': {'1m': Bar, '30s': Bar}, ...}
        self.prev_bar = {}                # {'XBTUSD': {'1m': Bar, '30s': Bar}, ...}

    def add_event_q(self, event_q):
        self.event_q = event_q                # 全局事件队列
        
    def run(self):
        self.__construct_bm_ws_market()
        self.td_run = threading.Thread(target=self.__run)
        self.active = True
        self.td_run.start()

    def __run(self):  
        while self.active:
            try:
                data = self.market_data_q.get(timeout=10)
            except queue.Empty:
                self.logger.warning('no data in market_data_q for 10 seconds')
            else:
                if isinstance(data, Tick):
                    self.processTick(data)
                elif isinstance(data, Orderbook):
                    self.processOrderbook(data)
                else:
                    self.logger.warning('Invalid data type from market_data_q: %s' % data.__class__)
    
    def stop(self):
        self.logger.info('Stopping DataHandler ...')
        self.bm_ws_market.exit()
        if True:
            self.logger.info('Exiting Thread: _DataHandler.__run(), wait for less than 10 secs')
            self.active = False
            self.td_run.join()
        self.logger.info('DataHandler stopped')

    def __construct_bm_ws_market(self):
        self.bm_ws_market = bitmexWSMarket2(apiKey=None, apiSecret=None, 
                                            is_test=self.g.is_test, loglevel=self.g.loglevel, logfile=self.g.logfile)
        self.bm_ws_market.connect()
        self.bm_ws_market.add_market_data_q(self.market_data_q)
        for s in self.symbols:
            self.bm_ws_market.subscribe(s, trade=True, orderbook=True)
        self.bm_ws_market.wait_for_data()

    def processTick(self, tick):
        self.logger.debug('💛 💛 💛 Processing Tick... %s' % tick)
        self.event_q.put(tick)   # todo, temp, for test

        # 顺序： bar_close_event, bar_open_event, tick_event

        # 0. 生成bar
        if self.registered_bar_events.get(tick.symbol):
            if self.get_current_tick(tick.symbol) is None:   # 边缘情况：如果是第一个Tick
                # self.__update_tick(tick)
                self.__init_bar(tick.symbol, tick)
            else:
                self.__bar(tick)

        # 1. 更新tick(last_price)
        self.__update_tick(tick)
        
        # 2. if 该symbol订阅了tick事件，推送（全局事件队列）
        if False:
            self.__push_tick_event(tick.symbol)
    
    def processOrderbook(self, ob):
        self.logger.debug('💜 💜 💜️ Processing Orderbook... %s' % ob)
        self.event_q.put(ob)    # todo, temp, for test
        
        # 1. 更新Orderbook
        self.__update_orderbook(ob)
        
        # 2. if 该symbol订阅了orderbook事件，推送（全局事件队列）
        if False:
            self.__push_orderbook_event(tick.symbol)   # TODO: register_tick/orderbook_event

    def __update_tick(self, tick):
        tick.receive_time = now()
        self.tick[tick.symbol] = tick

    def __update_orderbook(self, ob):
        ob.receive_time = now()
        self.orderbook[ob.symbol] = ob

    def __push_tick_event(self, symbol):
        pass
    
    def __push_orderbook_event(self, symbol):
        pass
    
    def register_bar_event(self, symbol, bar_type):
        """生成何种类型的bar

        更新 self.registered_bar_events,  which is {symbol: ['1m', '30s'], ...}
        初始化 self.bar, self.prev_bar
        """
        if symbol not in self.symbols:
            self.logger.warning('registering symbol "%s" of bar_type "%s", '
                                'but symbol not in self.symbols: %s' % (symbol, bar_type, self.symbols))
            return
        if symbol not in self.registered_bar_events:
            self.registered_bar_events[symbol] = []
            self.bar[symbol] = {}
            self.prev_bar[symbol] = {}
        if bar_type not in self.registered_bar_events[symbol]:
            self.registered_bar_events[symbol].append(bar_type)
            self.logger.info('Registered. %s: %s' % (symbol, bar_type))
            self.bar[symbol][bar_type] = Bar()
            self.prev_bar[symbol][bar_type] = Bar()
        else:
            self.logger.info('Registering bar: bar_type "%s" already exist in symbol "%s"' % (bar_type, symbol))

    def __init_bar(self, symbol, tick):
        """得到该symbol的一个tick时被调用。
        用tick初始化所有bar_type的第一个bar
        """
        if symbol in self.bar:
            for bar_type in self.bar[symbol]:
                td, ts = calculate_td_ts(tick.timestamp, bar_type)
                bar = Bar(symbol=symbol, bar_type=bar_type, td=td, ts=ts, open=tick.price, high=tick.price, low=tick.price)
                self.bar[symbol][bar_type] = bar
                self.logger.debug('💙 __init_bar() 💙 self.bar: %s' % self.bar)
                prev_bar = Bar(symbol=symbol, bar_type=bar_type, td=td, ts=ts-1)
                self.prev_bar[symbol][bar_type] = prev_bar
                self.logger.info('💙 __init_bar() 💙 self.prev_bar: %s' % self.prev_bar)

    def __bar(self, tick):
        symbol = tick.symbol
        bar_types = self.registered_bar_events[symbol]

        for bar_type in bar_types:

            current_bar = self.get_current_bar(symbol, bar_type)
            current_tick = self.get_current_tick(symbol)  # 注意此时tick还未更新
            assert isinstance(current_bar, Bar), 'current_bar.__class__ is %s' % current_bar.__class__
            assert isinstance(current_tick, Tick), 'current_tick.__class__ is %s' % current_tick.__class__

            td, ts = calculate_td_ts(tick.timestamp, bar_type)

            if (td, ts) > (current_bar.td, current_bar.ts):
                # bar_close
                current_bar.close = current_tick.price
                current_bar.receive_time = now()
                self.prev_bar[symbol][bar_type] = current_bar  # move to prev_bar
                self.bar[symbol][bar_type] = None
                self.__push_bar_close_event()
                # bar_open
                self.bar[symbol][bar_type] = Bar(symbol=symbol, bar_type=bar_type, td=td, ts=ts,
                                                 open=tick.price, high=tick.price, low=tick.price, close=None,
                                                 timestamp=tick.timestamp, receive_time=None)
                self.__push_bar_open_event()
            else:
                self.bar[symbol][bar_type].high = max(tick.price, current_bar.high)
                self.bar[symbol][bar_type].low = min(tick.price, current_bar.low)

    def __push_bar_close_event(self):
        self.event_q.put('💙 💙 💙  bar_close event, self.prev_bar is %s' % self.prev_bar)
        pass

    def __push_bar_open_event(self):
        self.event_q.put('💙 💙 💙  bar_open event, self.bar is %s' % self.bar)
        pass

    def get_current_bar(self, symbol, bar_type):
        try:
            return self.bar.get(symbol).get(bar_type)
        except AttributeError:
            return None

    def get_prev_bar(self, symbol, bar_type):
        try:
            return self.prev_bar.get(symbol).get(bar_type)
        except AttributeError:
            return None

    def get_current_tick(self, symbol):
        return self.tick.get(symbol)

    def snapshot(self, symbol):
        """参照国内期货快照数据结构"""
        pass
    
    