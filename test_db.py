import sqlite3
from datetime import date, timedelta

def get_conn():
    conn = sqlite3.connect("smart_lab.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def show_stock():
    conn = get_conn()
    rows = conn.execute("""
        SELECT c.id, c.name, l.name AS lab, c.available_quantity, c.total_quantity
        FROM components c JOIN labs l ON c.lab_id = l.id
    """).fetchall()
    for r in rows:
        print(f'{r["id"]}. {r["name"]} | {r["lab"]} | {r["available_quantity"]}/{r["total_quantity"]}')
    conn.close()

def issue_component(user_id, component_id, qty, days=7):
    conn = get_conn()
    comp = conn.execute("SELECT available_quantity FROM components WHERE id = ?",
                        (component_id,)).fetchone()
    if comp is None or comp["available_quantity"] < qty:
        conn.close()
        return "Not enough stock"
    today = date.today()
    conn.execute(
        "INSERT INTO issues (user_id, component_id, quantity, issue_date, due_date) VALUES (?,?,?,?,?)",
        (user_id, component_id, qty, str(today), str(today + timedelta(days=days))))
    conn.execute("UPDATE components SET available_quantity = available_quantity - ? WHERE id = ?",
                 (qty, component_id))
    conn.commit()
    conn.close()
    return "Issued"

print("STOCK BEFORE")
show_stock()
print(issue_component(1, 1, 2))   # student 1 takes 2 Arduino Uno
print("STOCK AFTER")
show_stock()