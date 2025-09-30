async function fetchRisk() {
  try {
    const r = await fetch('/api/risk_config');
    const data = await r.json();
    document.getElementById('max_orders_per_hour').value = data.max_orders_per_hour ?? 30;
    document.getElementById('max_daily_loss').value = data.max_daily_loss ?? 0;
    document.getElementById('max_position').value = data.max_position ?? 0;
  } catch (e) {
    console.log('risk fetch error', e);
  }
}

async function saveRisk() {
  const msg = document.getElementById('msg');
  msg.textContent = 'Saving...';
  try {
    const payload = {
      max_orders_per_hour: parseInt(document.getElementById('max_orders_per_hour').value || '30', 10),
      max_daily_loss: parseFloat(document.getElementById('max_daily_loss').value || '0'),
      max_position: parseFloat(document.getElementById('max_position').value || '0'),
    };
    const r = await fetch('/api/risk_config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await r.json();
    if (data.ok) {
      msg.textContent = 'Saved ✅';
    } else {
      msg.textContent = 'Error: ' + (data.error || 'unknown');
    }
  } catch (e) {
    msg.textContent = 'Error: ' + e;
  }
}

document.addEventListener('DOMContentLoaded', fetchRisk);
