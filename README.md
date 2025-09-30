# Koinonia

## Run (Windows, PowerShell)

### Backend: Flask
```powershell
$env:FLASK_APP="server.py"
$env:FLASK_RUN_PORT=5000
flask run

#-----Backend/FastApi------
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

#----Frontend-------
cd frontend
npm install
npm run dev
