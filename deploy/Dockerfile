# ── Stage 1: build frontend ──────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ── Stage 2: backend + built frontend ────────────────────
FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
# built frontend lands in backend/app/static (vite build outDir)
COPY --from=frontend /app/backend/app/static ./backend/app/static

WORKDIR /app/backend
ENV HOST=0.0.0.0 PORT=8000 DATABASE_URL=sqlite:////app/data/speaking_tutor.db
EXPOSE 8000

VOLUME ["/app/data"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
