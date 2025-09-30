function formatMoney(x){ return (x==null?'-':Number(x).toFixed(2)); }
function calcMaxLoss(order){
  if(!order || !order.orderLegCollection || !order.orderLegCollection.length) return null;
  const legs = order.orderLegCollection;
  const qty = legs[0].quantity||1;
  if(order.orderType==='NET_DEBIT') return Math.abs(order.price)*100*qty;
  if(order.orderType==='LIMIT' && legs[0].instrument && legs[0].instrument.assetType==='OPTION' && legs[0].instruction.includes('BUY')){
    return Math.abs(order.price)*100*qty;
  }
  return null;
}
async function suggestPrice(kind, symbol){
  const r = await fetch('/api/price/suggest', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind, symbol})});
  return r.json();
}
async function buildPreviewPlace(p){
  const suggested = await suggestPrice('option', p.suggested_contract);
  const limit = suggested.mid || 0.10;
  const payload = { kind: 'option', occ_symbol: p.suggested_contract, quantity: 1, limit_price: limit, instruction: 'BUY_TO_OPEN' };
  const built = await fetch('/api/order/build', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)}).then(r=>r.json());
  if(!built.ok){ alert('Build failed: '+(built.error||'unknown')); return; }
  const prev = await fetch('/api/order/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({order: built.order})}).then(r=>r.json());
  if(prev.error){ alert('Preview failed: '+prev.error); return; }
  const maxLoss = calcMaxLoss({ ...built.order });
  const lines = ['Order Preview','Symbol: '+p.symbol,'Contract: '+p.suggested_contract,'Limit: $'+formatMoney(limit),'Score: '+p.score,'Max loss est: $'+formatMoney(maxLoss),'Paper mode: '+prev.paper_mode];
  if(!confirm(lines.join('\n')+'\n\nPlace order now?')) return;
  const placed = await fetch('/api/order/place', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({order: built.order})}).then(r=>r.json());
  alert('Place: '+JSON.stringify(placed));
}
window.AI_ENHANCED = { buildPreviewPlace };
