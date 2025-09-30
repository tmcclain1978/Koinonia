def test_trade_validate_basic(client):
    r = client.post('/api/trade/validate', json={'symbol':'AAPL','side':'BUY','orderType':'LIMIT','quantity':10,'limitPrice':123.45})
    assert r.status_code == 200
    j = r.get_json(); assert j['ok'] is True and j['data']['normalized']['quantity']==10
def test_trade_validate_bracket(client):
    r = client.post('/api/trade/validate', json={'symbol':'AAPL','side':'BUY','orderType':'LIMIT','quantity':1,'limitPrice':100,'takeProfit':110,'stopLoss':95})
    assert r.status_code == 200 and r.get_json()['ok'] is True
def test_trade_validate_rejects_bad_qty(client):
    r = client.post('/api/trade/validate', json={'symbol':'AAPL','side':'BUY','orderType':'MARKET','quantity':0})
    assert r.status_code in (400, 429)
