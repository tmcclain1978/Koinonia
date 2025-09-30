V16 — Security Hardening (Individual mode, path to Multi-tenant)

Adds:
- security.py (RBAC, CSRF, rate limit, token encryption, headers)
- server.py hooks to enforce headers, CSRF on admin, rate-limit and restrict trade endpoints

Apply:
1) Copy files or run apply_delta.sh
2) Set env vars (.env.example)
3) Restart app

Admin CSRF (forms):
<form method="post" onsubmit="this.querySelector('[name=X-CSRF-Token]').value=document.cookie.split('; ').find(s=>s.startsWith('csrf_token='))?.split('=')[1]?.split('.')[0]||''">
  <input type="hidden" name="X-CSRF-Token">
  <!-- fields... -->
</form>

AJAX POSTs: send header X-CSRF-Token with the cookie's prefix value.
