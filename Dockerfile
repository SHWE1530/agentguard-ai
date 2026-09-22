# Backend image. The frontend is served separately by Vite in development.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

# Build the dataset, train the model and seed demo data at image build time so
# the container starts with a populated, ready-to-demo system.
RUN python -m backend.ml.generate_dataset \
 && python -m backend.ml.train_model \
 && python -m backend.app.database.seed

EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
