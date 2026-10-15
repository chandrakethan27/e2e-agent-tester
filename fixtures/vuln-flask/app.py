"""Tiny Shop API — a deliberately vulnerable fixture for E2E Agent Tester. Do not deploy."""

import sqlite3

from flask import Flask, jsonify, request

app = Flask(__name__)
API_SECRET = "9f2c7e4b1a8d6f3e0c5b7a9d2e4f6a8c1b3d5e7f"  # deliberately hard-coded for the fixture
DB = "/tmp/shop.db"


def init_db():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
    if not con.execute("SELECT COUNT(*) FROM products").fetchone()[0]:
        con.executemany("INSERT INTO products (name, price) VALUES (?, ?)", [("apple", 1.0), ("banana", 0.5), ("cherry", 3.0)])
    con.commit()
    con.close()


def rows_to_json(rows):
    return jsonify([{"id": r[0], "name": r[1], "price": r[2]} for r in rows])


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/products")
def products():
    con = sqlite3.connect(DB)
    return rows_to_json(con.execute("SELECT id, name, price FROM products").fetchall())


@app.get("/search")
def search():
    q = request.args.get("q", "")
    con = sqlite3.connect(DB)
    # SQL injection on purpose: the fixture's known vulnerability.
    return rows_to_json(con.execute(f"SELECT id, name, price FROM products WHERE name = '{q}'").fetchall())


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
