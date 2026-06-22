FROM python:3.11-slim

WORKDIR /app

# Зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходный код
COPY . .

ENV PYTHONUNBUFFERED=1

# Миграции + запуск бота
CMD ["sh", "-c", "alembic upgrade head && python main.py"]
