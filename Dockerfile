FROM python:3.12-slim

WORKDIR /bot

COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]
