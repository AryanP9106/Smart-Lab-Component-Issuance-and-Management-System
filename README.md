# Smart Lab Component Issuance and Management System

A Flask + SQLite REST API backend and lightweight web client for managing university lab hardware inventory, component requests, approvals, handovers, returns, overdue tracking, and audit logs.

## Tech Stack
- **Backend**: Python, Flask (Application Factory + Blueprints), Flask-JWT-Extended, Flask-CORS, Werkzeug
- **Database**: SQLite (`smart_lab.sqlite`) with foreign keys enabled
- **Frontend**: Responsive HTML5 / CSS3 / Vanilla JS SPA (`frontend/`) communicating via Fetch + JWT Bearer tokens

## Quick Start

1. **Activate virtual environment & install dependencies** (if not already installed):
   ```bash
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Initialize / migrate the database** (also runs automatically on app startup):
   ```bash
   python db_setup.py
   ```

3. **Run the server**:
   ```bash
   python run.py
   ```
   Open `http://localhost:5000` in your browser for the web dashboard, or hit the REST API directly.

4. **Run automated tests**:
   ```bash
   python -m unittest discover -s tests -v
   ```

## Demo Accounts
| Role | Email | Password |
| :--- | :--- | :--- |
| Student | `student@test.com` | `student123` |
| Faculty | `faculty@test.com` | `faculty123` |
| Lab Incharge | `incharge@test.com` | `incharge123` |
| Admin | `admin@test.com` | `admin123` |

## API Endpoints

### Health & Auth (`/auth`)
- `GET /health` — Service health check
- `POST /auth/register` — Register a new user (`student`, `faculty`, `incharge`, `admin`)
- `POST /auth/login` — Authenticate and receive JWT `access_token`
- `GET /auth/me` — Current user profile (JWT required)
- `GET /auth/users` — List all users (`admin`)
- `PUT /auth/users/<id>/role` — Update a user's role (`admin`)

### Catalog (`/catalog`)
- `GET /catalog/labs` — List all labs
- `POST /catalog/labs` — Create a lab (`incharge`, `admin`)
- `PUT /catalog/labs/<id>` — Update a lab (`incharge`, `admin`)
- `DELETE /catalog/labs/<id>` — Delete an empty lab (`admin`)
- `GET /catalog/components` — List components (supports `?lab_id=`, `?category=`, `?available=true|false`, `?q=`)
- `GET /catalog/components/<id>` — Component details
- `POST /catalog/components` — Add a component (`incharge`, `admin`)
- `PUT /catalog/components/<id>` — Update component specs/stock (`incharge`, `admin`)
- `DELETE /catalog/components/<id>` — Archive (if issue history exists) or delete a component (`admin`)

### Component Issuance (`/issues`)
- `POST /issues/request` — Submit a component request (`student`, `faculty`, `incharge`, `admin`)
- `GET /issues/my` — View your own requests and borrowings
- `GET /issues` — List all issues with filters (`faculty`, `incharge`, `admin`)
- `GET /issues/pending` — List pending requests (`faculty`, `incharge`, `admin`)
- `POST /issues/<id>/approve` — Approve a pending request (`faculty`, `incharge`, `admin`)
- `POST /issues/<id>/reject` — Reject a pending/approved request (`faculty`, `incharge`, `admin`)
- `POST /issues/<id>/issue` — Confirm physical handover and deduct stock (`incharge`, `admin`)
- `POST /issues/<id>/return` — Record return (`intact`, `damaged`, `missing`) and update stock (`incharge`, `admin`)

### Reports (`/reports`)
- `GET /reports/summary` — Inventory KPIs, low-stock alerts (`?low_stock=5`), and per-lab breakdown (`faculty`, `incharge`, `admin`)
- `GET /reports/overdue` — Overdue unreturned items (`faculty`, `incharge`, `admin`)
- `GET /reports/activity-log` — Audit trail of actions (`incharge`, `admin`)
