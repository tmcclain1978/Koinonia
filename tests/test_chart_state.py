def test_chart_state_roundtrip(client):
    r = client.get('/api/chart/state?symbol=AAPL&interval=1m')
    assert r.status_code == 200
    j = r.get_json(); assert j.get('ok') is True
    payload = {'symbol':'AAPL','interval':'1m','drawings':[{'type':'line','points':[[0,0],[1,1]]}],'overlays':{'ema':[9,20]},'tool':'cursor','compare':['MSFT','TSLA'],'percentScale':True}
    r2 = client.post('/api/chart/state', json=payload)
    assert r2.status_code == 200
    assert r2.get_json().get('ok') is True
