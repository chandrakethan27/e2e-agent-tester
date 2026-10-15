# Tiny Shop API

A small product catalogue API.

## Run

    pip install -r requirements.txt
    python app.py

The API listens on port 5000.

## Endpoints

- `GET /health` — health check
- `GET /products` — list all products
- `GET /search?q=apple` — find a product by exact name

## Why use it

- Search is safe against injection attacks.
- Handles 1000 requests per second on a laptop.
- Zero configuration.
