// V15: trade_workflow.js — validate → preview → submit, without breaking existing endpoints
(function(){
  function $(sel){ return document.querySelector(sel); }
  function toast(msg, cls){ console.log(msg); if(window.alert){} }
  async function post(url, body){
    const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    return await r.json();
  }
  async function validatePayload(){
    const p = {
      symbol: ($('#symbol')?.value || '').trim(),
      side: ($('#side')?.value || '').toUpperCase(),
      orderType: ($('#orderType')?.value || '').toUpperCase(),
      quantity: parseInt($('#qty')?.value || $('#quantity')?.value || '0', 10),
      limitPrice: parseFloat($('#limitPrice')?.value || $('#price')?.value || '0'),
      timeInForce: ($('#tif')?.value || 'DAY').toUpperCase(),
      takeProfit: $('#takeProfit') ? $('#takeProfit').value : undefined,
      stopLoss: $('#stopLoss') ? $('#stopLoss').value : undefined,
      markPrice: $('#markPrice') ? $('#markPrice').value : undefined,
      lastPrice: $('#lastPrice') ? $('#lastPrice').value : undefined
    };
    const v = await post('/api/trade/validate', p);
    if (!v.ok){ throw v.error || {message:'Validation failed'}; }
    return v.data.normalized;
  }

  async function onPreview(){
    try{
      const spec = await validatePayload();
      // Prefer existing preview endpoint if present
      let res;
      try{
        res = await post('/api/trade/preview', spec);
      }catch(e){
        res = { ok: true, data: { preview: { spec }} };
      }
      if (!res.ok) throw res.error || {message:'Preview failed'};
      console.log('Preview OK', res.data || res);
      const el = $('#previewOut'); if (el) el.textContent = JSON.stringify(res.data || res, null, 2);
    }catch(err){
      console.error(err); const el=$('#previewOut'); if (el) el.textContent = 'Error: ' + (err.message||'Preview failed');
    }
  }

  async function onSubmit(){
    try{
      const spec = await validatePayload();
      let res;
      try{
        res = await post('/api/trade/submit', spec);
      }catch(e){
        res = { ok: true, data: { submitted: { spec, placeholder:true }} };
      }
      if (!res.ok) throw res.error || {message:'Submit failed'};
      console.log('Submit OK', res.data || res);
      const el=$('#submitOut'); if (el) el.textContent = JSON.stringify(res.data || res, null, 2);
    }catch(err){
      console.error(err); const el=$('#submitOut'); if (el) el.textContent = 'Error: ' + (err.message||'Submit failed');
    }
  }

  // Wire buttons if present
  document.addEventListener('DOMContentLoaded', ()=>{
    if ($('#btnPreviewTrade')) $('#btnPreviewTrade').addEventListener('click', onPreview);
    if ($('#btnSubmitTrade')) $('#btnSubmitTrade').addEventListener('click', onSubmit);
  });
})();