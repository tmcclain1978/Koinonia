import os, json, time
def test_analytics_overview(client, tmp_path, monkeypatch):
    audit_dir = tmp_path / 'data' / 'audit'; audit_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({'ts': int(time.time())-10, 'pnl': 50.0, 'strategy':'straddle'}),
        json.dumps({'ts': int(time.time())-5, 'pnl': -20.0, 'strategy':'straddle'}),
        json.dumps({'ts': int(time.time())-1, 'entry_price':100, 'exit_price':102, 'qty':1, 'side':'BUY', 'strategy':'covered'}),
    ]
    (audit_dir / 'sample.jsonl').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    r = client.get('/api/analytics/overview?range=7d')
    assert r.status_code == 200 and r.get_json()['ok'] is True
