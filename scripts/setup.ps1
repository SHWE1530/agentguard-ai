# One-shot local setup for Windows PowerShell.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "==> Installing Python dependencies"
pip install -r requirements.txt

Write-Host "==> Generating the synthetic behavioural dataset"
python -m backend.ml.generate_dataset

Write-Host "==> Training the Isolation Forest anomaly detector"
python -m backend.ml.train_model

Write-Host "==> Seeding demo data"
python -m backend.app.database.seed

Write-Host "==> Installing frontend dependencies"
Set-Location frontend
npm install

Write-Host ""
Write-Host "Setup complete. Run the backend and frontend in two terminals:"
Write-Host "  uvicorn backend.app.main:app --reload"
Write-Host "  cd frontend; npm run dev"
