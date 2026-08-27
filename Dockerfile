FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE="route_fuel_v2.settings"

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Collect static files into the image so WhiteNoise can serve them directly.
RUN python manage.py collectstatic --noinput

RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
CMD ["web"]
