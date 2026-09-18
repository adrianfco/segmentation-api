FROM python:3.12.14-slim-bookworm

RUN groupadd --system app \
    && useradd --system --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
ENV PIP_ROOT_USER_ACTION=ignore

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
