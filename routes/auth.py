import sqlite3
from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from app.auth_utils import current_user_id, roles_required
from app.db import get_db, log_activity

auth_bp = Blueprint("auth", __name__)
VALID_ROLES = {"student", "faculty", "incharge", "admin"}


def _serialize_user(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "enrollment_no": row["enrollment_no"],
        "email": row["email"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = (data.get("role") or "student").strip().lower()
    enrollment_no = data.get("enrollment_no")
    enrollment_no = (
        enrollment_no.strip()
        if isinstance(enrollment_no, str) and enrollment_no.strip()
        else None
    )

    if not name or not email or not password:
        return jsonify({"error": "name, email, and password are required"}), 400

    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    if role not in VALID_ROLES:
        return jsonify({"error": f"role must be one of {sorted(VALID_ROLES)}"}), 400

    password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    conn = get_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO users (name, enrollment_no, email, password_hash, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, enrollment_no, email, password_hash, role),
        )
        user_id = cur.lastrowid
        log_activity(
            conn,
            user_id,
            "user_registered",
            "user",
            user_id,
            f"Registered {email} as {role}",
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.close()
        return jsonify({"error": f"Duplicate or invalid user data: {exc}"}), 400

    user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return jsonify({"message": "User registered", "user": _serialize_user(user_row)}), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = create_access_token(
        identity=str(user["id"]),
        additional_claims={"role": user["role"], "name": user["name"]},
    )
    return jsonify({"access_token": token, "user": _serialize_user(user)}), 200


@auth_bp.get("/me")
@jwt_required()
def me():
    uid = current_user_id()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    if user is None:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"user": _serialize_user(user)}), 200


@auth_bp.get("/users")
@roles_required("admin")
def list_users():
    role_filter = (request.args.get("role") or "").strip().lower()
    conn = get_db()
    if role_filter:
        rows = conn.execute(
            "SELECT * FROM users WHERE role = ? ORDER BY id ASC", (role_filter,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
    conn.close()
    return jsonify({"users": [_serialize_user(r) for r in rows]}), 200


@auth_bp.put("/users/<int:user_id>/role")
@roles_required("admin")
def update_user_role(user_id):
    data = request.get_json(silent=True) or {}
    new_role = (data.get("role") or "").strip().lower()
    if new_role not in VALID_ROLES:
        return jsonify({"error": f"role must be one of {sorted(VALID_ROLES)}"}), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    log_activity(
        conn,
        current_user_id(),
        "user_role_updated",
        "user",
        user_id,
        f"Changed {user['email']} role from {user['role']} to {new_role}",
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return jsonify({"message": "User role updated", "user": _serialize_user(updated)}), 200
