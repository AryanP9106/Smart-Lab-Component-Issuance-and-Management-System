import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app import create_app
from app.db import get_db


class SmartLabAPITestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_smart_lab.sqlite"
        self.app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.db_path),
                "JWT_SECRET_KEY": "smart-lab-unit-test-secret-key-at-least-32-bytes",
                "SEED_SAMPLE_DATA": True,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def login(self, email, password):
        res = self.client.post(
            "/auth/login", json={"email": email, "password": password}
        )
        self.assertEqual(res.status_code, 200, res.get_json())
        return res.get_json()["access_token"]

    def auth_headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_health_and_frontend(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        home.close()

    def test_register_login_me_and_admin_role_management(self):
        reg = self.client.post(
            "/auth/register",
            json={
                "name": "Aryan Pattani",
                "email": "aryan@test.com",
                "enrollment_no": "92400957041",
                "password": "password123",
                "role": "student",
            },
        )
        self.assertEqual(reg.status_code, 201)
        new_user_id = reg.get_json()["user"]["id"]

        student_token = self.login("aryan@test.com", "password123")
        me = self.client.get("/auth/me", headers=self.auth_headers(student_token))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["user"]["email"], "aryan@test.com")

        # Student cannot list all users
        denied = self.client.get("/auth/users", headers=self.auth_headers(student_token))
        self.assertEqual(denied.status_code, 403)

        # Admin can list users and promote role
        admin_token = self.login("admin@test.com", "admin123")
        users_res = self.client.get("/auth/users", headers=self.auth_headers(admin_token))
        self.assertEqual(users_res.status_code, 200)
        self.assertGreaterEqual(len(users_res.get_json()["users"]), 5)

        role_res = self.client.put(
            f"/auth/users/{new_user_id}/role",
            headers=self.auth_headers(admin_token),
            json={"role": "faculty"},
        )
        self.assertEqual(role_res.status_code, 200)
        self.assertEqual(role_res.get_json()["user"]["role"], "faculty")

    def test_catalog_crud_and_rbac(self):
        student_token = self.login("student@test.com", "student123")
        incharge_token = self.login("incharge@test.com", "incharge123")
        admin_token = self.login("admin@test.com", "admin123")

        # Public listing works
        labs_res = self.client.get("/catalog/labs")
        self.assertEqual(labs_res.status_code, 200)
        self.assertGreaterEqual(len(labs_res.get_json()["labs"]), 2)

        # Student forbidden from adding labs
        forbidden = self.client.post(
            "/catalog/labs",
            headers=self.auth_headers(student_token),
            json={"name": "Unauthorized Lab"},
        )
        self.assertEqual(forbidden.status_code, 403)

        # Incharge creates lab + component
        lab_res = self.client.post(
            "/catalog/labs",
            headers=self.auth_headers(incharge_token),
            json={"name": "VLSI Lab", "location": "Block C, Floor 1"},
        )
        self.assertEqual(lab_res.status_code, 201)
        lab_id = lab_res.get_json()["lab"]["id"]

        comp_res = self.client.post(
            "/catalog/components",
            headers=self.auth_headers(incharge_token),
            json={
                "name": "FPGA Dev Board",
                "category": "FPGA",
                "description": "Xilinx Artix-7 trainer kit",
                "lab_id": lab_id,
                "total_quantity": 4,
            },
        )
        self.assertEqual(comp_res.status_code, 201)
        comp_id = comp_res.get_json()["component"]["id"]

        # Search filter works
        search_res = self.client.get("/catalog/components?q=FPGA&available=true")
        self.assertEqual(search_res.status_code, 200)
        self.assertEqual(len(search_res.get_json()["components"]), 1)

        # Update component
        upd_res = self.client.put(
            f"/catalog/components/{comp_id}",
            headers=self.auth_headers(incharge_token),
            json={"total_quantity": 6, "available_quantity": 6},
        )
        self.assertEqual(upd_res.status_code, 200)
        self.assertEqual(upd_res.get_json()["component"]["available_quantity"], 6)

        # Incharge cannot delete component (admin only)
        del_denied = self.client.delete(
            f"/catalog/components/{comp_id}",
            headers=self.auth_headers(incharge_token),
        )
        self.assertEqual(del_denied.status_code, 403)

        # Admin deletes unused component and empty lab
        del_ok = self.client.delete(
            f"/catalog/components/{comp_id}",
            headers=self.auth_headers(admin_token),
        )
        self.assertEqual(del_ok.status_code, 200)
        self.assertTrue(del_ok.get_json()["deleted"])

        lab_del = self.client.delete(
            f"/catalog/labs/{lab_id}",
            headers=self.auth_headers(admin_token),
        )
        self.assertEqual(lab_del.status_code, 200)

    def test_full_issue_lifecycle_and_stock_integrity(self):
        student_token = self.login("student@test.com", "student123")
        faculty_token = self.login("faculty@test.com", "faculty123")
        incharge_token = self.login("incharge@test.com", "incharge123")

        # Initial stock for Arduino Uno (id=1) is 20
        before = self.client.get("/catalog/components/1").get_json()["component"]
        self.assertEqual(before["available_quantity"], 20)

        # 1. Student requests 3 Arduino Unos
        req = self.client.post(
            "/issues/request",
            headers=self.auth_headers(student_token),
            json={"component_id": 1, "quantity": 3, "days": 10, "purpose": "Smart Car"},
        )
        self.assertEqual(req.status_code, 201)
        issue_id = req.get_json()["issue"]["id"]
        self.assertEqual(req.get_json()["issue"]["status"], "pending")

        # Student sees it in /issues/my
        my_res = self.client.get("/issues/my", headers=self.auth_headers(student_token))
        self.assertEqual(my_res.status_code, 200)
        self.assertEqual(len(my_res.get_json()["issues"]), 1)

        # 2. Faculty approves request
        pending = self.client.get(
            "/issues/pending", headers=self.auth_headers(faculty_token)
        )
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(len(pending.get_json()["issues"]), 1)

        app_res = self.client.post(
            f"/issues/{issue_id}/approve",
            headers=self.auth_headers(faculty_token),
            json={"note": "Approved for semester project"},
        )
        self.assertEqual(app_res.status_code, 200)
        self.assertEqual(app_res.get_json()["issue"]["status"], "approved")

        # Faculty cannot perform physical handover (incharge/admin only)
        handover_denied = self.client.post(
            f"/issues/{issue_id}/issue",
            headers=self.auth_headers(faculty_token),
            json={},
        )
        self.assertEqual(handover_denied.status_code, 403)

        # 3. Incharge hands out component -> stock drops from 20 to 17
        handover = self.client.post(
            f"/issues/{issue_id}/issue",
            headers=self.auth_headers(incharge_token),
            json={},
        )
        self.assertEqual(handover.status_code, 200)
        self.assertEqual(handover.get_json()["issue"]["status"], "issued")

        mid = self.client.get("/catalog/components/1").get_json()["component"]
        self.assertEqual(mid["available_quantity"], 17)

        # 4. Incharge records return (1 damaged, 2 restocked)
        ret = self.client.post(
            f"/issues/{issue_id}/return",
            headers=self.auth_headers(incharge_token),
            json={
                "condition_status": "damaged",
                "restock_quantity": 2,
                "condition_note": "1 board voltage regulator burnt",
            },
        )
        self.assertEqual(ret.status_code, 200)
        self.assertEqual(ret.get_json()["issue"]["status"], "returned")
        self.assertEqual(ret.get_json()["restocked_quantity"], 2)

        after = self.client.get("/catalog/components/1").get_json()["component"]
        self.assertEqual(after["available_quantity"], 19)

    def test_reports_summary_overdue_and_activity_log(self):
        student_token = self.login("student@test.com", "student123")
        incharge_token = self.login("incharge@test.com", "incharge123")

        # Create & issue a component, then backdate due_date to simulate overdue
        req = self.client.post(
            "/issues/request",
            headers=self.auth_headers(student_token),
            json={"component_id": 6, "quantity": 2, "days": 5, "purpose": "Edge AI"},
        )
        issue_id = req.get_json()["issue"]["id"]
        self.client.post(
            f"/issues/{issue_id}/issue",
            headers=self.auth_headers(incharge_token),
            json={},
        )

        past_due = (date.today() - timedelta(days=3)).isoformat()
        conn = get_db()
        conn.execute("UPDATE issues SET due_date = ? WHERE id = ?", (past_due, issue_id))
        conn.commit()
        conn.close()

        summary = self.client.get(
            "/reports/summary?low_stock=5",
            headers=self.auth_headers(incharge_token),
        )
        self.assertEqual(summary.status_code, 200)
        sdata = summary.get_json()
        self.assertEqual(sdata["overview"]["overdue_count"], 1)
        self.assertGreaterEqual(len(sdata["low_stock_items"]), 1)

        overdue = self.client.get(
            "/reports/overdue", headers=self.auth_headers(incharge_token)
        )
        self.assertEqual(overdue.status_code, 200)
        self.assertEqual(overdue.get_json()["count"], 1)
        self.assertEqual(overdue.get_json()["overdue"][0]["days_overdue"], 3)

        logs = self.client.get(
            "/reports/activity-log", headers=self.auth_headers(incharge_token)
        )
        self.assertEqual(logs.status_code, 200)
        self.assertGreaterEqual(len(logs.get_json()["logs"]), 2)


if __name__ == "__main__":
    unittest.main()
