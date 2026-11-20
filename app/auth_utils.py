from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required


def current_user_id():
    return int(get_jwt_identity())


def current_user_role():
    return (get_jwt().get("role") or "").lower()


def roles_required(*allowed_roles):
    normalized = {r.lower() for r in allowed_roles}

    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            role = current_user_role()
            if role not in normalized:
                return (
                    jsonify(
                        {
                            "error": "Forbidden: insufficient permissions",
                            "required_roles": sorted(normalized),
                            "your_role": role,
                        }
                    ),
                    403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
