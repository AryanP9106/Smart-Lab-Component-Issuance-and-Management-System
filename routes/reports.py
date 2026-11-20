from datetime import date
from flask import Blueprint, jsonify, request

from app.auth_utils import roles_required
from app.db import get_db

reports_bp = Blueprint("reports", __name__)


@reports_bp.get("/summary")
@roles_required("faculty", "incharge", "admin")
def summary_report():
    low_stock_threshold = request.args.get("low_stock", default=5, type=int)
    if low_stock_threshold is None or low_stock_threshold < 0:
        low_stock_threshold = 5

    today_str = date.today().isoformat()
    conn = get_db()

    total_labs = conn.execute("SELECT COUNT(*) FROM labs").fetchone()[0]
    comp_stats = conn.execute(
        """
        SELECT COUNT(*) AS component_types,
               COALESCE(SUM(total_quantity), 0) AS total_units,
               COALESCE(SUM(available_quantity), 0) AS available_units
        FROM components
        WHERE is_active = 1
        """
    ).fetchone()

    status_counts = {
        row["status"]: row["cnt"]
        for row in conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM issues GROUP BY status"
        ).fetchall()
    }

    issued_units = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM issues WHERE status = 'issued'"
    ).fetchone()[0]

    overdue_count = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status = 'issued' AND due_date < ?",
        (today_str,),
    ).fetchone()[0]

    low_stock_rows = conn.execute(
        """
        SELECT c.id, c.name, c.category, l.name AS lab_name,
               c.available_quantity, c.total_quantity
        FROM components c
        JOIN labs l ON l.id = c.lab_id
        WHERE c.is_active = 1 AND c.available_quantity <= ?
        ORDER BY c.available_quantity ASC, c.name ASC
        """,
        (low_stock_threshold,),
    ).fetchall()

    lab_rows = conn.execute(
        """
        SELECT l.id, l.name, l.location,
               COUNT(CASE WHEN c.is_active = 1 THEN 1 END) AS component_types,
               COALESCE(SUM(CASE WHEN c.is_active = 1 THEN c.total_quantity ELSE 0 END), 0) AS total_units,
               COALESCE(SUM(CASE WHEN c.is_active = 1 THEN c.available_quantity ELSE 0 END), 0) AS available_units
        FROM labs l
        LEFT JOIN components c ON c.lab_id = l.id
        GROUP BY l.id
        ORDER BY l.name ASC
        """
    ).fetchall()
    conn.close()

    return (
        jsonify(
            {
                "overview": {
                    "total_labs": total_labs,
                    "total_component_types": comp_stats["component_types"],
                    "total_units": comp_stats["total_units"],
                    "available_units": comp_stats["available_units"],
                    "currently_issued_units": issued_units,
                    "active_issues": status_counts.get("issued", 0),
                    "pending_requests": status_counts.get("pending", 0),
                    "approved_requests": status_counts.get("approved", 0),
                    "returned_issues": status_counts.get("returned", 0),
                    "rejected_requests": status_counts.get("rejected", 0),
                    "overdue_count": overdue_count,
                },
                "low_stock_threshold": low_stock_threshold,
                "low_stock_items": [dict(r) for r in low_stock_rows],
                "lab_breakdown": [dict(r) for r in lab_rows],
            }
        ),
        200,
    )


@reports_bp.get("/overdue")
@roles_required("faculty", "incharge", "admin")
def overdue_report():
    today = date.today()
    today_str = today.isoformat()
    conn = get_db()
    rows = conn.execute(
        """
        SELECT i.id, i.user_id, u.name AS user_name, u.email AS user_email,
               u.enrollment_no, u.role AS user_role,
               i.component_id, c.name AS component_name,
               l.name AS lab_name, i.quantity, i.issue_date, i.due_date
        FROM issues i
        JOIN users u ON u.id = i.user_id
        JOIN components c ON c.id = i.component_id
        JOIN labs l ON l.id = c.lab_id
        WHERE i.status = 'issued' AND i.due_date < ?
        ORDER BY i.due_date ASC
        """,
        (today_str,),
    ).fetchall()
    conn.close()

    overdue_items = []
    for r in rows:
        item = dict(r)
        item["days_overdue"] = (today - date.fromisoformat(r["due_date"])).days
        overdue_items.append(item)

    return jsonify({"count": len(overdue_items), "overdue": overdue_items}), 200


@reports_bp.get("/activity-log")
@roles_required("incharge", "admin")
def activity_log():
    limit = request.args.get("limit", default=50, type=int) or 50
    limit = max(1, min(limit, 200))
    action = (request.args.get("action") or "").strip()
    entity_type = (request.args.get("entity_type") or "").strip()

    clauses = []
    params = []
    if action:
        clauses.append("a.action = ?")
        params.append(action)
    if entity_type:
        clauses.append("a.entity_type = ?")
        params.append(entity_type)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT a.id, a.actor_id, u.name AS actor_name, u.role AS actor_role,
               a.action, a.entity_type, a.entity_id, a.details, a.created_at
        FROM activity_logs a
        LEFT JOIN users u ON u.id = a.actor_id
        {where_sql}
        ORDER BY a.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    conn.close()
    return jsonify({"logs": [dict(r) for r in rows]}), 200
