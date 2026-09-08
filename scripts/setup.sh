#!/usr/bin/env bash
# One-shot local setup: dependencies, dataset, model, demo data.
set -e
cd "$(dirname "$0")/.."

echo "==> Installing Python dependencies"
pip install -r requirements.txt

echo "==> Generating the synthetic behavioural dataset"
python -m backend.ml.generate_dataset

echo "==> Training the Isolation Forest anomaly detector"
python -m backend.ml.train_model

echo "==> Seeding demo data"
python -m backend.app.database.seed

echo "==> Installing frontend dependencies"
cd frontend && npm install

echo
echo "Setup complete. Run the backend and frontend in two terminals:"
echo "  uvicorn backend.app.main:app --reload"
echo "  cd frontend && npm run dev"
