from datetime import date, timedelta
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.auth_utils import current_user_id, roles_required
from app.db import get_db, log_activity

issues_bp = Blueprint("issues", __name__)
VALID_CONDITIONS = {"intact", "damaged", "missing"}

ISSUE_SELECT_SQL = """
SELECT i.id, i.user_id, u.name AS user_name, u.email AS user_email,
       u.enrollment_no, u.role AS user_role,
       i.component_id, c.name AS component_name, c.category AS component_category,
       l.id AS lab_id, l.name AS lab_name,
       i.quantity, i.request_date, i.issue_date, i.due_date, i.return_date,
       i.requested_days, i.status, i.purpose, i.condition_status, i.condition_note,
       i.reviewed_by, i.issued_by, i.returned_to
FROM issues i
JOIN users u ON u.id = i.user_id
JOIN components c ON c.id = i.component_id
JOIN labs l ON l.id = c.lab_id
"""


def _serialize_issue(row):
    today_str = date.today().isoformat()
    is_overdue = (
        row["status"] == "issued"
        and row["due_date"] is not None
        and row["due_date"] < today_str
    )
    days_overdue = 0
    if is_overdue:
        days_overdue = (date.today() - date.fromisoformat(row["due_date"])).days

    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "user_email": row["user_email"],
        "enrollment_no": row["enrollment_no"],
        "user_role": row["user_role"],
        "component_id": row["component_id"],
        "component_name": row["component_name"],
        "component_category": row["component_category"],
        "lab_id": row["lab_id"],
        "lab_name": row["lab_name"],
        "quantity": row["quantity"],
        "request_date": row["request_date"],
        "issue_date": row["issue_date"],
        "due_date": row["due_date"],
        "return_date": row["return_date"],
        "requested_days": row["requested_days"],
        "status": row["status"],
        "purpose": row["purpose"],
        "condition_status": row["condition_status"],
        "condition_note": row["condition_note"],
        "reviewed_by": row["reviewed_by"],
        "issued_by": row["issued_by"],
        "returned_to": row["returned_to"],
        "is_overdue": is_overdue,
        "days_overdue": days_overdue,
    }


def _fetch_issue(conn, issue_id):
    return conn.execute(f"{ISSUE_SELECT_SQL} WHERE i.id = ?", (issue_id,)).fetchone()


@issues_bp.post("/request")
@roles_required("student", "faculty", "incharge", "admin")
def request_component():
    data = request.get_json(silent=True) or {}
    component_id = data.get("component_id")
    quantity = data.get("quantity")
    days = data.get("days", 7)
    purpose = (data.get("purpose") or "").strip() or None

    if component_id is None or quantity is None:
        return jsonify({"error": "component_id and quantity are required"}), 400

    try:
        component_id = int(component_id)
        quantity = int(quantity)
        days = int(days)
    except (TypeError, ValueError):
        return jsonify({"error": "component_id, quantity, and days must be integers"}), 400

    if quantity <= 0:
        return jsonify({"error": "quantity must be greater than 0"}), 400
    if days < 1 or days > 30:
        return jsonify({"error": "days must be between 1 and 30"}), 400

    conn = get_db()
    comp = conn.execute(
        "SELECT id, name, available_quantity, is_active FROM components WHERE id = ?",
        (component_id,),
    ).fetchone()
    if comp is None or not comp["is_active"]:
        conn.close()
        return jsonify({"error": "Component not found or inactive"}), 404

    if comp["available_quantity"] < quantity:
        conn.close()
        return (
            jsonify(
                {
                    "error": "Insufficient stock available for this request",
                    "available_quantity": comp["available_quantity"],
                }
            ),
            400,
        )

    uid = current_user_id()
    today_str = date.today().isoformat()
    cur = conn.execute(
        """
        INSERT INTO issues (user_id, component_id, quantity, request_date, requested_days, status, purpose)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
        (uid, component_id, quantity, today_str, days, purpose),
    )
    issue_id = cur.lastrowid
    log_activity(
        conn,
        uid,
        "issue_requested",
        "issue",
        issue_id,
        f"Requested {quantity}x {comp['name']} for {days} days",
    )
    conn.commit()
    issue_row = _fetch_issue(conn, issue_id)
    conn.close()
    return jsonify({"message": "Component request submitted", "issue": _serialize_issue(issue_row)}), 201


@issues_bp.get("/my")
@jwt_required()
def my_issues():
    uid = current_user_id()
    status_filter = (request.args.get("status") or "").strip().lower()

    clauses = ["i.user_id = ?"]
    params = [uid]
    if status_filter:
        clauses.append("i.status = ?")
        params.append(status_filter)

    conn = get_db()
    rows = conn.execute(
        f"{ISSUE_SELECT_SQL} WHERE {' AND '.join(clauses)} ORDER BY i.id DESC",
        params,
    ).fetchall()
    conn.close()
    return jsonify({"issues": [_serialize_issue(r) for r in rows]}), 200


@issues_bp.get("")
@roles_required("faculty", "incharge", "admin")
def list_all_issues():
    status_filter = (request.args.get("status") or "").strip().lower()
    user_id = request.args.get("user_id", type=int)
    component_id = request.args.get("component_id", type=int)
    lab_id = request.args.get("lab_id", type=int)
    overdue_only = (request.args.get("overdue") or "").strip().lower() == "true"

    clauses = []
    params = []

    if status_filter:
        clauses.append("i.status = ?")
        params.append(status_filter)
    if user_id is not None:
        clauses.append("i.user_id = ?")
        params.append(user_id)
    if component_id is not None:
        clauses.append("i.component_id = ?")
        params.append(component_id)
    if lab_id is not None:
        clauses.append("c.lab_id = ?")
        params.append(lab_id)
    if overdue_only:
        clauses.append("i.status = 'issued' AND i.due_date < ?")
        params.append(date.today().isoformat())

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_db()
    rows = conn.execute(
        f"{ISSUE_SELECT_SQL} {where_sql} ORDER BY i.id DESC", params
    ).fetchall()
    conn.close()
    return jsonify({"issues": [_serialize_issue(r) for r in rows]}), 200


@issues_bp.get("/pending")
@roles_required("faculty", "incharge", "admin")
def list_pending_issues():
    include_approved = (request.args.get("include_approved") or "").strip().lower() == "true"
    conn = get_db()
    if include_approved:
        rows = conn.execute(
            f"{ISSUE_SELECT_SQL} WHERE i.status IN ('pending', 'approved') ORDER BY i.id ASC"
        ).fetchall()
    else:
        rows = conn.execute(
            f"{ISSUE_SELECT_SQL} WHERE i.status = 'pending' ORDER BY i.id ASC"
        ).fetchall()
    conn.close()
    return jsonify({"issues": [_serialize_issue(r) for r in rows]}), 200


@issues_bp.post("/<int:issue_id>/approve")
@roles_required("faculty", "incharge", "admin")
def approve_issue(issue_id):
    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip() or None

    conn = get_db()
    issue = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if issue is None:
        conn.close()
        return jsonify({"error": "Issue request not found"}), 404

    if issue["status"] != "pending":
        conn.close()
        return jsonify({"error": f"Cannot approve request with status '{issue['status']}'"}), 400

    comp = conn.execute(
        "SELECT name, available_quantity FROM components WHERE id = ?",
        (issue["component_id"],),
    ).fetchone()
    if comp["available_quantity"] < issue["quantity"]:
        conn.close()
        return (
            jsonify(
                {
                    "error": "Insufficient stock to approve request",
                    "available_quantity": comp["available_quantity"],
                }
            ),
            400,
        )

    actor_id = current_user_id()
    conn.execute(
        """
        UPDATE issues
        SET status = 'approved', reviewed_by = ?,
            condition_note = COALESCE(?, condition_note)
        WHERE id = ?
        """,
        (actor_id, note, issue_id),
    )
    log_activity(
        conn,
        actor_id,
        "issue_approved",
        "issue",
        issue_id,
        f"Approved request #{issue_id} ({issue['quantity']}x {comp['name']})",
    )
    conn.commit()
    row = _fetch_issue(conn, issue_id)
    conn.close()
    return jsonify({"message": "Request approved", "issue": _serialize_issue(row)}), 200


@issues_bp.post("/<int:issue_id>/reject")
@roles_required("faculty", "incharge", "admin")
def reject_issue(issue_id):
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or data.get("note") or "").strip() or None

    conn = get_db()
    issue = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if issue is None:
        conn.close()
        return jsonify({"error": "Issue request not found"}), 404

    if issue["status"] not in ("pending", "approved"):
        conn.close()
        return jsonify({"error": f"Cannot reject request with status '{issue['status']}'"}), 400

    actor_id = current_user_id()
    conn.execute(
        """
        UPDATE issues
        SET status = 'rejected', reviewed_by = ?, condition_note = ?
        WHERE id = ?
        """,
        (actor_id, reason, issue_id),
    )
    log_activity(
        conn,
        actor_id,
        "issue_rejected",
        "issue",
        issue_id,
        f"Rejected request #{issue_id}" + (f": {reason}" if reason else ""),
    )
    conn.commit()
    row = _fetch_issue(conn, issue_id)
    conn.close()
    return jsonify({"message": "Request rejected", "issue": _serialize_issue(row)}), 200


@issues_bp.post("/<int:issue_id>/issue")
@roles_required("incharge", "admin")
def handover_issue(issue_id):
    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip() or None

    conn = get_db()
    issue = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if issue is None:
        conn.close()
        return jsonify({"error": "Issue request not found"}), 404

    if issue["status"] not in ("approved", "pending"):
        conn.close()
        return jsonify({"error": f"Cannot issue request with status '{issue['status']}'"}), 400

    days = data.get("days", issue["requested_days"] or 7)
    try:
        days = int(days)
    except (TypeError, ValueError):
        conn.close()
        return jsonify({"error": "days must be an integer"}), 400
    if days < 1 or days > 30:
        conn.close()
        return jsonify({"error": "days must be between 1 and 30"}), 400

    cur = conn.execute(
        """
        UPDATE components
        SET available_quantity = available_quantity - ?
        WHERE id = ? AND is_active = 1 AND available_quantity >= ?
        """,
        (issue["quantity"], issue["component_id"], issue["quantity"]),
    )
    if cur.rowcount == 0:
        conn.close()
        return jsonify({"error": "Insufficient stock available to issue component"}), 400

    today = date.today()
    due_date = today + timedelta(days=days)
    actor_id = current_user_id()

    conn.execute(
        """
        UPDATE issues
        SET status = 'issued',
            issue_date = ?,
            due_date = ?,
            issued_by = ?,
            reviewed_by = COALESCE(reviewed_by, ?),
            condition_note = COALESCE(?, condition_note)
        WHERE id = ?
        """,
        (today.isoformat(), due_date.isoformat(), actor_id, actor_id, note, issue_id),
    )

    comp_name = conn.execute(
        "SELECT name FROM components WHERE id = ?", (issue["component_id"],)
    ).fetchone()["name"]
    log_activity(
        conn,
        actor_id,
        "issue_handed_out",
        "issue",
        issue_id,
        f"Issued {issue['quantity']}x {comp_name} (due {due_date.isoformat()})",
    )
    conn.commit()
    row = _fetch_issue(conn, issue_id)
    conn.close()
    return jsonify({"message": "Component issued", "issue": _serialize_issue(row)}), 200


@issues_bp.post("/<int:issue_id>/return")
@roles_required("incharge", "admin")
def return_issue(issue_id):
    data = request.get_json(silent=True) or {}
    condition_status = (data.get("condition_status") or "intact").strip().lower()
    condition_note = (data.get("condition_note") or data.get("note") or "").strip() or None

    if condition_status not in VALID_CONDITIONS:
        return (
            jsonify({"error": f"condition_status must be one of {sorted(VALID_CONDITIONS)}"}),
            400,
        )

    conn = get_db()
    issue = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if issue is None:
        conn.close()
        return jsonify({"error": "Issue record not found"}), 404

    if issue["status"] != "issued":
        conn.close()
        return jsonify({"error": f"Cannot return item with status '{issue['status']}'"}), 400

    default_restock = issue["quantity"] if condition_status == "intact" else 0
    restock_qty = data.get("restock_quantity", default_restock)
    try:
        restock_qty = int(restock_qty)
    except (TypeError, ValueError):
        conn.close()
        return jsonify({"error": "restock_quantity must be an integer"}), 400

    if restock_qty < 0 or restock_qty > issue["quantity"]:
        conn.close()
        return (
            jsonify(
                {"error": f"restock_quantity must be between 0 and {issue['quantity']}"}
            ),
            400,
        )

    if restock_qty > 0:
        conn.execute(
            """
            UPDATE components
            SET available_quantity = MIN(total_quantity, available_quantity + ?)
            WHERE id = ?
            """,
            (restock_qty, issue["component_id"]),
        )

    today_str = date.today().isoformat()
    actor_id = current_user_id()
    conn.execute(
        """
        UPDATE issues
        SET status = 'returned',
            return_date = ?,
            condition_status = ?,
            condition_note = COALESCE(?, condition_note),
            returned_to = ?
        WHERE id = ?
        """,
        (today_str, condition_status, condition_note, actor_id, issue_id),
    )

    comp_name = conn.execute(
        "SELECT name FROM components WHERE id = ?", (issue["component_id"],)
    ).fetchone()["name"]
    log_activity(
        conn,
        actor_id,
        "issue_returned",
        "issue",
        issue_id,
        f"Returned {issue['quantity']}x {comp_name} ({condition_status}, restocked {restock_qty})",
    )
    conn.commit()
    row = _fetch_issue(conn, issue_id)
    conn.close()
    return (
        jsonify(
            {
                "message": "Component return recorded",
                "restocked_quantity": restock_qty,
                "issue": _serialize_issue(row),
            }
        ),
        200,
    )
