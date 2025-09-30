async function cancelOrder(id){
  const r = await fetch('/api/order/cancel', {method:'POST', headers:{'Content-Type':'application/json','Authorization': 'Bearer '+(localStorage.ADMIN_API_TOKEN||'')}, body: JSON.stringify({order_id: id})});
  alert('Cancel: '+(await r.text()));
  loadAll();
}
async function replaceOrder(id, newPrice){
  const ok = confirm('Replace order '+id+' with new price '+newPrice+' ?');
  if(!ok) return;
  const body = { order_id: id, order: { price: parseFloat(newPrice) } };
  const r = await fetch('/api/order/replace', {method:'POST', headers:{'Content-Type':'application/json','Authorization': 'Bearer '+(localStorage.ADMIN_API_TOKEN||'')}, body: JSON.stringify(body)});
  alert('Replace: '+(await r.text()));
  loadAll();
}
function renderOrders(resp){
  const el = document.getElementById('orders');
  const data = (resp && resp.response) ? resp.response : resp || {};
  const arr = Array.isArray(data) ? data : (data.orders || data.orderStrategies || []);
  if(!arr || !arr.length){ el.innerText = 'No open orders'; return; }
  let html = '<table><thead><tr><th>ID</th><th>Symbol</th><th>Type</th><th>Price</th><th>Status</th><th>Actions</th></tr></thead><tbody>';
  for(const o of arr){
    const id = o.orderId || o.id || '';
    const price = o.price || (o.orderType==='LIMIT'?o.price:'-');
    const sym = (o.orderLegCollection && o.orderLegCollection[0] && o.orderLegCollection[0].instrument && o.orderLegCollection[0].instrument.symbol) || '-';
    html += `<tr><td>${id}</td><td>${sym}</td><td>${o.orderType||'-'}</td><td>${price||'-'}</td><td>${o.status||'-'}</td>` +
            `<td><button onclick="cancelOrder('${id}')">Cancel</button> ` +
            `<button onclick="(function(){ const p = prompt('New limit price?'); if(p){ replaceOrder('${id}', p); } })()">Replace</button></td></tr>`;
  }
  html += '</tbody></table>';
  el.innerHTML = html;
}
function renderPositions(resp){
  const el = document.getElementById('positions');
  const data = (resp && resp.response) ? resp.response : resp || {};
  el.innerText = JSON.stringify(data, null, 2);
}
async function loadAll(){
  const s = await fetch('/api/audit/summary').then(r=>r.json());
  document.getElementById('stats').innerText = JSON.stringify(s.counts, null, 2);
  const orders = await fetch('/api/orders').then(r=>r.json()).catch(_=>({}));
  const pos = await fetch('/api/positions').then(r=>r.json()).catch(_=>({}));
  const risk = await fetch('/api/positions/risk').then(r=>r.json()).catch(_=>({}));
  renderOrders(orders);
  renderPositions(pos);
  document.getElementById('audit').innerText = JSON.stringify(s.last, null, 2);
  document.getElementById('risk').innerText = JSON.stringify(risk, null, 2);
}
document.addEventListener('DOMContentLoaded', loadAll);
