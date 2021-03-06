# trade bot
#   strat: real-time moving average crossover (hour span)

import pandas as pd
import sqlalchemy
import ta
from binance.client import Client
from binance.exceptions import BinanceAPIException
from sqlalchemy import exc
from time import sleep
from math import floor
from keys import api_key, api_secret

def MAstrat(tradecoin, basecoin, amt, stop_loss, open_position = False):
    ST = 7
    LT = 20

    pair = tradecoin.upper() + basecoin.upper()
    
    qty = 0
    buyprice = 0

    stepSize = float(next((sub for sub in client.get_symbol_info(pair)['filters'] if sub['filterType'] == 'LOT_SIZE'), None)['stepSize'])
    
    try:
        dbres = pd.read_sql('Orders', engine)
        if dbres.empty != True:
            if dbres.iloc[-1].completed == False and dbres.iloc[-1].symbol == pair:
                print('Oper order founded!')
                buyprice = dbres.iloc[-1].price
                qty = dbres.iloc[-1].qty
                open_position = True
        else:
            print('No orders saved in database founded')
    except exc.SQLAlchemyError:
        print('SQLAlchemy error!')
    except:
        print('Something when wrong when trying to read orders on the database')
    
    trade = client.get_my_trades(symbol=pair, limit=1)
    actualQty = getcoinbalance(tradecoin)

    if len(trade) > 0 and trade[0]['isBuyer'] and actualQty > float(trade[0]['qty']):
        qty = float(trade[0]['qty'])
        buyprice = float(trade[0]['price'])
        open_position = True
        print('{} of {} buyed found! Trying to sell'.format(qty, tradecoin))
    else:
        print('No open orders found')

    while True:
        historicals = gethistoricals(pair, ST, LT)
        timer = 1800
        
        if not open_position:
            actualprice = float(client.get_margin_price_index(symbol=pair)['price'])
            qty = (amt / actualprice) - ((amt / actualprice) % stepSize)
            
            print('Price: {}, rsi: {}, ST/LT mov diff: {}'.format(historicals['Close'], round(historicals['rsi'], 3), round(historicals['ST'] - historicals['LT'], 3)))
            if historicals['ST'] > historicals['LT'] and historicals['rsi'] > 60:
                #print('buy')
                try:
                    print('Trying to buy {} {}'.format(qty, tradecoin.upper()))
                    buyorder = client.create_order(
                        symbol=pair,
                        side='BUY',
                        type='MARKET',
                        quantity= qty
                    )
                    buyprice = float(buyorder['fills'][0]['price'])
                    print('Buy at price: {}, stop: {}, min target: {}'.format(buyprice, round(buyprice * stop_loss, 2), round(buyprice * 1.01, 2)))
                    print(getfreebalances(tradecoin, basecoin))
                    frame = createorderframe(buyorder)
                    try:
                        frame.to_sql('Orders', engine, if_exists='append', index=False)
                        print('Order saved in data base')
                    except exc.SQLAlchemyError:
                        print('SQLAlchemy error!')
                    except:
                        print('Something when wrong when trying to save the order into the database')
                    open_position = True
                except BinanceAPIException as e:
                    print('Error: {} ({})'.format(e.message, e.status_code))
                
        if open_position:
            print('Actual win/loss: {}%, rsi: {}, ST/LT mov diff: {}'.format(round((((historicals['Close'] - buyprice)/buyprice)*100), 3), round(historicals['rsi'], 3), round(historicals['ST'] - historicals['LT'], 3)))
            if (historicals['LT'] > historicals['ST'] and historicals['rsi'] < 55 and historicals['Close'] > buyprice * 1.01) or (buyprice <= historicals['Close'] * stop_loss):
                #print('sell')
                try:
                    sellorder = client.create_order(
                        symbol=pair,
                        side='SELL',
                        type='MARKET',
                        quantity= qty
                    )
                    print('Sell at price: {}, stop: {}, target: {}'.format(buyprice, buyprice * stop_loss, buyprice * 1.01))
                    if buyprice != 0:
                        print('Win/loss: {}%'.format(round((float(sellorder['fills'][0]['price']) / buyprice - 1) * 100, 3)))
                    print(getfreebalances(tradecoin, basecoin))
                    # actualizar orden de base de datos
                    try:
                        dbres = pd.read_sql('Orders', engine)
                        if dbres.iloc[-1].symbol == pair:
                            sql = 'update Orders set completed = 1 where id = (select max(id) from Orders)'
                            engine.execute(sql)
                    except exc.SQLAlchemyError:
                        print('SQLAlchemy error!')
                    open_position = False
                    sleep(5)
                except BinanceAPIException as e:
                    print('Error: {} ({})'.format(e.message, e.status_code))
            else:
                open_position = True
        while (timer > 0):
            sleep(600)
            #print info data
            timer -= 600

def gethistoricals(pair, ST, LT):
    df = pd.DataFrame(client.get_historical_klines(pair, '30m', str(LT) + 'days ago UTC', '30m ago UTC'))
    closes = pd.DataFrame(df[4])
    closes.columns = ['Close']
    closes = closes.astype(float)
    closes['rsi'] = ta.momentum.rsi(closes.Close, window=14)
    closes['ST'] = closes.Close.rolling(window=ST).mean()
    closes['LT'] = closes.Close.rolling(window=LT).mean()
    #closes.dropna(inplace=True)
    closes = closes.iloc[-1]
    #print('Price: {}, rsi: {}, ST: {}, LT: {}'.format(closes['Close'], closes['rsi'], closes['ST'], closes['LT']))
    return closes

def createorderframe(msg):
    lastsell = msg['fills'][0]
    data = [{ "symbol": msg['symbol'], "qty": lastsell['qty'], "price": lastsell['price'], "commission": lastsell['commission'], "completed": False }]
    df = pd.DataFrame(data)
    df.qty = df.qty.astype(float)
    df.price = df.price.astype(float)
    df.commission = df.commission.astype(float)
    return df

def getfreebalances(*symbols):
    symbols = symbols[::-1]
    bal = 'Balances'
    for item in client.get_account()['balances']:
        for sym in symbols:
            if item['asset'] == sym.upper():
                bal += ' | {}: {}'.format(sym.upper(), item['free'])
    return bal

def getcoinbalance(symbol):
    value = 0
    for item in client.get_account()['balances']:
        if item['asset'] == symbol.upper():
            value = float(item['free'])
            break
    if value != 0:
        return value
    else:
        return None
    
def truncateprice(n, precs):
    return int(n * 10**precs) / 10**precs

def main(args=None):
    MAstrat('SOL', 'BUSD', 12, 0.95)
    #print(gethistoricals('SHIBBUSD', 7, 20))

if __name__ == '__main__':
    client = Client(api_key, api_secret)
    engine = sqlalchemy.create_engine('sqlite:///db/MACross.db')
    main()