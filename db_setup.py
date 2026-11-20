import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "smart_lab.sqlite"


def _table_columns(cur, table_name):
    return {row[1] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _needs_issues_migration(cur):
    row = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
    ).fetchone()
    if not row or not row[0]:
        return False
    ddl = row[0]
    return "'pending'" not in ddl or "reviewed_by" not in ddl


def init_db(db_path=None, seed_sample_data=True):
    target = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA foreign_keys = OFF")
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            enrollment_no TEXT UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('student','faculty','incharge','admin')),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS labs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            location TEXT
        );

        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'General',
            description TEXT,
            lab_id INTEGER NOT NULL,
            total_quantity INTEGER NOT NULL CHECK (total_quantity >= 0),
            available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (lab_id) REFERENCES labs(id)
        );

        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            component_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            request_date TEXT,
            issue_date TEXT,
            due_date TEXT,
            return_date TEXT,
            requested_days INTEGER NOT NULL DEFAULT 7 CHECK (requested_days > 0),
            status TEXT NOT NULL DEFAULT 'issued'
                CHECK (status IN ('pending','approved','rejected','issued','returned')),
            purpose TEXT,
            condition_status TEXT CHECK (condition_status IN ('intact','damaged','missing') OR condition_status IS NULL),
            condition_note TEXT,
            reviewed_by INTEGER,
            issued_by INTEGER,
            returned_to INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (component_id) REFERENCES components(id),
            FOREIGN KEY (reviewed_by) REFERENCES users(id),
            FOREIGN KEY (issued_by) REFERENCES users(id),
            FOREIGN KEY (returned_to) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (actor_id) REFERENCES users(id)
        );
        """
    )

    # Migrate existing older tables safely if present
    user_cols = _table_columns(cur, "users")
    if "created_at" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        cur.execute(
            "UPDATE users SET created_at = ? WHERE created_at IS NULL",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),),
        )

    comp_cols = _table_columns(cur, "components")
    if "category" not in comp_cols:
        cur.execute("ALTER TABLE components ADD COLUMN category TEXT NOT NULL DEFAULT 'General'")
    if "description" not in comp_cols:
        cur.execute("ALTER TABLE components ADD COLUMN description TEXT")
    if "is_active" not in comp_cols:
        cur.execute("ALTER TABLE components ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    if _needs_issues_migration(cur):
        cur.executescript(
            """
            CREATE TABLE issues_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                component_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                request_date TEXT,
                issue_date TEXT,
                due_date TEXT,
                return_date TEXT,
                requested_days INTEGER NOT NULL DEFAULT 7 CHECK (requested_days > 0),
                status TEXT NOT NULL DEFAULT 'issued'
                    CHECK (status IN ('pending','approved','rejected','issued','returned')),
                purpose TEXT,
                condition_status TEXT CHECK (condition_status IN ('intact','damaged','missing') OR condition_status IS NULL),
                condition_note TEXT,
                reviewed_by INTEGER,
                issued_by INTEGER,
                returned_to INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (component_id) REFERENCES components(id),
                FOREIGN KEY (reviewed_by) REFERENCES users(id),
                FOREIGN KEY (issued_by) REFERENCES users(id),
                FOREIGN KEY (returned_to) REFERENCES users(id)
            );

            INSERT INTO issues_new (
                id, user_id, component_id, quantity, request_date,
                issue_date, due_date, return_date, status, condition_note
            )
            SELECT
                id, user_id, component_id, quantity, issue_date,
                issue_date, due_date, return_date, status, condition_note
            FROM issues;

            DROP TABLE issues;
            ALTER TABLE issues_new RENAME TO issues;
            """
        )

    conn.execute("PRAGMA foreign_keys = ON")

    if seed_sample_data:
        cur.executemany(
            "INSERT OR IGNORE INTO labs (id, name, location) VALUES (?, ?, ?)",
            [
                (1, "Electronics Lab", "Block A, Floor 1"),
                (2, "IoT Lab", "Block A, Floor 2"),
                (3, "Robotics & Embedded Lab", "Block B, Floor 1"),
            ],
        )

        cur.executemany(
            """
            INSERT OR IGNORE INTO components
                (id, name, category, description, lab_id, total_quantity, available_quantity, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            [
                (1, "Arduino Uno", "Microcontroller", "ATmega328P development board with USB cable", 2, 20, 20),
                (2, "Ultrasonic Sensor", "Sensor", "HC-SR04 distance measuring module", 2, 15, 15),
                (3, "Breadboard", "Prototyping", "830-point solderless breadboard", 1, 30, 30),
                (4, "Jumper Wires Set", "Accessories", "Male-to-Male / Male-to-Female 40-pin bundle", 1, 40, 40),
                (5, "ESP32 DevKit", "Microcontroller", "Wi-Fi + Bluetooth dual-core IoT board", 2, 12, 12),
                (6, "Raspberry Pi 4 (4GB)", "Single Board Computer", "Quad-core edge compute board with power adapter", 3, 5, 5),
            ],
        )

        # Update categories/descriptions on pre-existing seed components if still default
        cur.execute("UPDATE components SET category = 'Microcontroller', description = 'ATmega328P development board with USB cable' WHERE id = 1 AND (description IS NULL OR category = 'General')")
        cur.execute("UPDATE components SET category = 'Sensor', description = 'HC-SR04 distance measuring module' WHERE id = 2 AND (description IS NULL OR category = 'General')")
        cur.execute("UPDATE components SET category = 'Prototyping', description = '830-point solderless breadboard' WHERE id = 3 AND (description IS NULL OR category = 'General')")
        cur.execute("UPDATE components SET category = 'Accessories', description = 'Male-to-Male / Male-to-Female 40-pin bundle' WHERE id = 4 AND (description IS NULL OR category = 'General')")

        demo_users = [
            (1, "Test Student", "92100000001", "student@test.com", "student123", "student"),
            (2, "Lab Incharge", None, "incharge@test.com", "incharge123", "incharge"),
            (3, "Dr. Faculty Guide", None, "faculty@test.com", "faculty123", "faculty"),
            (4, "System Admin", None, "admin@test.com", "admin123", "admin"),
        ]
        for uid, name, enroll, email, plain_pw, role in demo_users:
            existing = cur.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
            if existing is None:
                cur.execute(
                    """
                    INSERT INTO users (id, name, enrollment_no, email, password_hash, role)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (uid, name, enroll, email, generate_password_hash(plain_pw, method="pbkdf2:sha256"), role),
                )
            elif existing[1] == "temp":
                cur.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(plain_pw, method="pbkdf2:sha256"), existing[0]),
                )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized and migrated.")
