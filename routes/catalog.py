import sqlite3
from flask import Blueprint, jsonify, request

from app.auth_utils import current_user_id, roles_required
from app.db import get_db, log_activity

catalog_bp = Blueprint("catalog", __name__)


def _serialize_lab(row):
    data = {
        "id": row["id"],
        "name": row["name"],
        "location": row["location"],
    }
    if "component_count" in row.keys():
        data["component_count"] = row["component_count"]
    return data


def _serialize_component(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "description": row["description"],
        "lab_id": row["lab_id"],
        "lab_name": row["lab_name"],
        "lab_location": row["lab_location"],
        "total_quantity": row["total_quantity"],
        "available_quantity": row["available_quantity"],
        "is_active": bool(row["is_active"]),
    }


@catalog_bp.get("/labs")
def list_labs():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT l.id, l.name, l.location,
               COUNT(CASE WHEN c.is_active = 1 THEN 1 END) AS component_count
        FROM labs l
        LEFT JOIN components c ON c.lab_id = l.id
        GROUP BY l.id
        ORDER BY l.name ASC
        """
    ).fetchall()
    conn.close()
    return jsonify({"labs": [_serialize_lab(r) for r in rows]}), 200


@catalog_bp.post("/labs")
@roles_required("admin", "incharge")
def create_lab():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    location = (data.get("location") or "").strip() or None

    if not name:
        return jsonify({"error": "Lab name is required"}), 400

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO labs (name, location) VALUES (?, ?)", (name, location)
        )
        lab_id = cur.lastrowid
        log_activity(
            conn,
            current_user_id(),
            "lab_created",
            "lab",
            lab_id,
            f"Created lab '{name}' ({location or 'No location'})",
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": f"Lab '{name}' already exists"}), 400

    row = conn.execute("SELECT id, name, location FROM labs WHERE id = ?", (lab_id,)).fetchone()
    conn.close()
    return jsonify({"message": "Lab created", "lab": _serialize_lab(row)}), 201


@catalog_bp.put("/labs/<int:lab_id>")
@roles_required("admin", "incharge")
def update_lab(lab_id):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    lab = conn.execute("SELECT * FROM labs WHERE id = ?", (lab_id,)).fetchone()
    if lab is None:
        conn.close()
        return jsonify({"error": "Lab not found"}), 404

    name = (data.get("name") if "name" in data else lab["name"] or "").strip()
    location = (
        (data.get("location") or "").strip() or None
        if "location" in data
        else lab["location"]
    )
    if not name:
        conn.close()
        return jsonify({"error": "Lab name cannot be empty"}), 400

    try:
        conn.execute(
            "UPDATE labs SET name = ?, location = ? WHERE id = ?",
            (name, location, lab_id),
        )
        log_activity(
            conn,
            current_user_id(),
            "lab_updated",
            "lab",
            lab_id,
            f"Updated lab #{lab_id} to '{name}'",
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": f"Lab '{name}' already exists"}), 400

    updated = conn.execute("SELECT id, name, location FROM labs WHERE id = ?", (lab_id,)).fetchone()
    conn.close()
    return jsonify({"message": "Lab updated", "lab": _serialize_lab(updated)}), 200


@catalog_bp.delete("/labs/<int:lab_id>")
@roles_required("admin")
def delete_lab(lab_id):
    conn = get_db()
    lab = conn.execute("SELECT * FROM labs WHERE id = ?", (lab_id,)).fetchone()
    if lab is None:
        conn.close()
        return jsonify({"error": "Lab not found"}), 404

    comp_count = conn.execute(
        "SELECT COUNT(*) FROM components WHERE lab_id = ?", (lab_id,)
    ).fetchone()[0]
    if comp_count > 0:
        conn.close()
        return (
            jsonify(
                {
                    "error": "Cannot delete lab while components are assigned to it",
                    "component_count": comp_count,
                }
            ),
            400,
        )

    conn.execute("DELETE FROM labs WHERE id = ?", (lab_id,))
    log_activity(
        conn,
        current_user_id(),
        "lab_deleted",
        "lab",
        lab_id,
        f"Deleted lab '{lab['name']}'",
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Lab deleted", "lab_id": lab_id}), 200


@catalog_bp.get("/components")
def list_components():
    lab_id = request.args.get("lab_id", type=int)
    category = (request.args.get("category") or "").strip()
    available = (request.args.get("available") or "").strip().lower()
    keyword = (request.args.get("q") or "").strip()
    include_inactive = (request.args.get("include_inactive") or "").strip().lower() == "true"

    clauses = []
    params = []

    if not include_inactive:
        clauses.append("c.is_active = 1")
    if lab_id is not None:
        clauses.append("c.lab_id = ?")
        params.append(lab_id)
    if category:
        clauses.append("LOWER(c.category) = LOWER(?)")
        params.append(category)
    if available == "true":
        clauses.append("c.available_quantity > 0")
    elif available == "false":
        clauses.append("c.available_quantity = 0")
    if keyword:
        like = f"%{keyword}%"
        clauses.append(
            "(c.name LIKE ? OR c.category LIKE ? OR COALESCE(c.description, '') LIKE ? OR l.name LIKE ?)"
        )
        params.extend([like, like, like, like])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT c.id, c.name, c.category, c.description, c.lab_id,
               l.name AS lab_name, l.location AS lab_location,
               c.total_quantity, c.available_quantity, c.is_active
        FROM components c
        JOIN labs l ON l.id = c.lab_id
        {where_sql}
        ORDER BY l.name ASC, c.name ASC
        """,
        params,
    ).fetchall()
    conn.close()
    return jsonify({"components": [_serialize_component(r) for r in rows]}), 200


@catalog_bp.get("/components/<int:component_id>")
def get_component(component_id):
    conn = get_db()
    row = conn.execute(
        """
        SELECT c.id, c.name, c.category, c.description, c.lab_id,
               l.name AS lab_name, l.location AS lab_location,
               c.total_quantity, c.available_quantity, c.is_active
        FROM components c
        JOIN labs l ON l.id = c.lab_id
        WHERE c.id = ?
        """,
        (component_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "Component not found"}), 404
    return jsonify({"component": _serialize_component(row)}), 200


@catalog_bp.post("/components")
@roles_required("admin", "incharge")
def create_component():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "General").strip() or "General"
    description = (data.get("description") or "").strip() or None
    lab_id = data.get("lab_id")
    total_quantity = data.get("total_quantity")
    available_quantity = data.get("available_quantity", total_quantity)

    if not name or lab_id is None or total_quantity is None:
        return jsonify({"error": "name, lab_id, and total_quantity are required"}), 400

    try:
        lab_id = int(lab_id)
        total_quantity = int(total_quantity)
        available_quantity = int(available_quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "lab_id, total_quantity, and available_quantity must be integers"}), 400

    if total_quantity < 0 or available_quantity < 0 or available_quantity > total_quantity:
        return (
            jsonify(
                {"error": "Quantities must satisfy 0 <= available_quantity <= total_quantity"}
            ),
            400,
        )

    conn = get_db()
    lab = conn.execute("SELECT id FROM labs WHERE id = ?", (lab_id,)).fetchone()
    if lab is None:
        conn.close()
        return jsonify({"error": "Specified lab_id does not exist"}), 404

    cur = conn.execute(
        """
        INSERT INTO components (name, category, description, lab_id, total_quantity, available_quantity, is_active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (name, category, description, lab_id, total_quantity, available_quantity),
    )
    component_id = cur.lastrowid
    log_activity(
        conn,
        current_user_id(),
        "component_created",
        "component",
        component_id,
        f"Added '{name}' (qty {available_quantity}/{total_quantity}) to lab #{lab_id}",
    )
    conn.commit()

    row = conn.execute(
        """
        SELECT c.id, c.name, c.category, c.description, c.lab_id,
               l.name AS lab_name, l.location AS lab_location,
               c.total_quantity, c.available_quantity, c.is_active
        FROM components c
        JOIN labs l ON l.id = c.lab_id
        WHERE c.id = ?
        """,
        (component_id,),
    ).fetchone()
    conn.close()
    return jsonify({"message": "Component created", "component": _serialize_component(row)}), 201


@catalog_bp.put("/components/<int:component_id>")
@roles_required("admin", "incharge")
def update_component(component_id):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM components WHERE id = ?", (component_id,)
    ).fetchone()
    if existing is None:
        conn.close()
        return jsonify({"error": "Component not found"}), 404

    name = (data.get("name") if "name" in data else existing["name"] or "").strip()
    category = (
        (data.get("category") or "General").strip()
        if "category" in data
        else existing["category"]
    )
    description = (
        (data.get("description") or "").strip() or None
        if "description" in data
        else existing["description"]
    )

    try:
        lab_id = int(data["lab_id"]) if "lab_id" in data else existing["lab_id"]
        total_quantity = (
            int(data["total_quantity"])
            if "total_quantity" in data
            else existing["total_quantity"]
        )
        available_quantity = (
            int(data["available_quantity"])
            if "available_quantity" in data
            else existing["available_quantity"]
        )
    except (TypeError, ValueError):
        conn.close()
        return jsonify({"error": "lab_id, total_quantity, and available_quantity must be integers"}), 400

    is_active = (
        (1 if bool(data["is_active"]) else 0)
        if "is_active" in data
        else existing["is_active"]
    )

    if not name:
        conn.close()
        return jsonify({"error": "Component name cannot be empty"}), 400

    if total_quantity < 0 or available_quantity < 0 or available_quantity > total_quantity:
        conn.close()
        return (
            jsonify(
                {"error": "Quantities must satisfy 0 <= available_quantity <= total_quantity"}
            ),
            400,
        )

    lab = conn.execute("SELECT id FROM labs WHERE id = ?", (lab_id,)).fetchone()
    if lab is None:
        conn.close()
        return jsonify({"error": "Specified lab_id does not exist"}), 404

    conn.execute(
        """
        UPDATE components
        SET name = ?, category = ?, description = ?, lab_id = ?,
            total_quantity = ?, available_quantity = ?, is_active = ?
        WHERE id = ?
        """,
        (
            name,
            category,
            description,
            lab_id,
            total_quantity,
            available_quantity,
            is_active,
            component_id,
        ),
    )
    log_activity(
        conn,
        current_user_id(),
        "component_updated",
        "component",
        component_id,
        f"Updated '{name}' (stock {available_quantity}/{total_quantity})",
    )
    conn.commit()

    row = conn.execute(
        """
        SELECT c.id, c.name, c.category, c.description, c.lab_id,
               l.name AS lab_name, l.location AS lab_location,
               c.total_quantity, c.available_quantity, c.is_active
        FROM components c
        JOIN labs l ON l.id = c.lab_id
        WHERE c.id = ?
        """,
        (component_id,),
    ).fetchone()
    conn.close()
    return jsonify({"message": "Component updated", "component": _serialize_component(row)}), 200


@catalog_bp.delete("/components/<int:component_id>")
@roles_required("admin")
def delete_component(component_id):
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM components WHERE id = ?", (component_id,)
    ).fetchone()
    if existing is None:
        conn.close()
        return jsonify({"error": "Component not found"}), 404

    active_issues = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE component_id = ? AND status = 'issued'",
        (component_id,),
    ).fetchone()[0]
    if active_issues > 0:
        conn.close()
        return (
            jsonify(
                {
                    "error": "Cannot decommission component while units are currently issued",
                    "active_issues": active_issues,
                }
            ),
            400,
        )

    history_count = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE component_id = ?", (component_id,)
    ).fetchone()[0]

    if history_count > 0:
        conn.execute(
            "UPDATE components SET is_active = 0, available_quantity = 0 WHERE id = ?",
            (component_id,),
        )
        log_activity(
            conn,
            current_user_id(),
            "component_archived",
            "component",
            component_id,
            f"Archived component '{existing['name']}' (retained due to {history_count} issue records)",
        )
        conn.commit()
        conn.close()
        return (
            jsonify(
                {
                    "message": "Component archived (has historical issue records)",
                    "component_id": component_id,
                    "archived": True,
                }
            ),
            200,
        )

    conn.execute("DELETE FROM components WHERE id = ?", (component_id,))
    log_activity(
        conn,
        current_user_id(),
        "component_deleted",
        "component",
        component_id,
        f"Deleted component '{existing['name']}'",
    )
    conn.commit()
    conn.close()
    return (
        jsonify(
            {
                "message": "Component deleted",
                "component_id": component_id,
                "deleted": True,
            }
        ),
        200,
    )
