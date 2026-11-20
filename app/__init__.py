import os
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from app import db as db_module
from db_setup import init_db
from routes.auth import auth_bp
from routes.catalog import catalog_bp
from routes.issues import issues_bp
from routes.reports import reports_bp

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


def create_app(config=None):
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = os.environ.get(
        "JWT_SECRET_KEY", "smart-lab-dev-secret-key-change-in-production-32b"
    )
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=12)

    if config:
        app.config.update(config)

    if "DB_PATH" in app.config:
        db_module.DB_PATH = Path(app.config["DB_PATH"])
    else:
        db_module.DB_PATH = BASE_DIR / "smart_lab.sqlite"

    init_db(db_module.DB_PATH, seed_sample_data=app.config.get("SEED_SAMPLE_DATA", True))

    CORS(app)
    jwt = JWTManager(app)

    @jwt.unauthorized_loader
    def handle_missing_token(reason):
        return jsonify({"error": f"Authentication required: {reason}"}), 401

    @jwt.invalid_token_loader
    def handle_invalid_token(reason):
        return jsonify({"error": f"Invalid token: {reason}"}), 401

    @jwt.expired_token_loader
    def handle_expired_token(jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired. Please log in again."}), 401

    @app.errorhandler(400)
    def bad_request(err):
        return jsonify({"error": str(err)}), 400

    @app.errorhandler(404)
    def not_found(err):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(500)
    def internal_error(err):
        return jsonify({"error": "Internal server error"}), 500

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(catalog_bp, url_prefix="/catalog")
    app.register_blueprint(issues_bp, url_prefix="/issues")
    app.register_blueprint(reports_bp, url_prefix="/reports")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "smart-lab-backend"}), 200

    @app.get("/")
    def index():
        if (FRONTEND_DIR / "index.html").exists():
            return send_from_directory(FRONTEND_DIR, "index.html")
        return jsonify({"status": "ok", "message": "Smart Lab API is running"}), 200

    @app.get("/<path:filename>")
    def serve_frontend_static(filename):
        target = FRONTEND_DIR / filename
        if target.is_file():
            return send_from_directory(FRONTEND_DIR, filename)
        return jsonify({"error": "Resource not found"}), 404

    return app
