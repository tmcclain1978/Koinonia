def test_sse_smoke(client):
    r = client.get('/api/chart/stream?symbol=AAPL&interval=1m')
    assert r.status_code == 200
    assert 'text/event-stream' in r.content_type
