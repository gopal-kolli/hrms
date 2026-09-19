"""Native Frappe integration coverage for the optional employee credit workflow."""

import os
from unittest import skipUnless

import frappe
from frappe.utils import add_days, getdate, today

from hrms.api import comp_off
from hrms.hr.doctype.compensatory_leave_request.test_compensatory_leave_request import (
	create_holiday_list,
	mark_attendance,
)
from hrms.hr.doctype.holiday_list_assignment.test_holiday_list_assignment import (
	create_holiday_list_assignment,
)
from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
from hrms.hr.doctype.leave_period.test_leave_period import create_leave_period
from hrms.tests.utils import HRMSTestSuite


class TestCompOffPortal(HRMSTestSuite):
	def setUp(self):
		frappe.set_user("Administrator")
		self.previous_flag = frappe.conf.get("enable_comp_off_self_service")
		frappe.conf.enable_comp_off_self_service = 1
		self.addCleanup(self.cleanup)
		for key in ("employee", "manager", "other"):
			email = f"comp-off-{key}@example.com"
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": key,
						"send_welcome_email": 0,
						"roles": [{"role": "Employee"}],
					}
				).insert()
			doc = frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": f"Comp Off {key}",
					"company": "_Test Company",
					"status": "Active",
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"user_id": email,
					"create_user_permission": 0,
				}
			).insert()
			setattr(self, key, doc)
		self.employee.db_set("reports_to", self.manager.name)
		create_leave_period(add_days(today(), -30), add_days(today(), 60), "_Test Company")
		create_holiday_list()
		create_holiday_list_assignment("Employee", self.employee.name, "_Test Compensatory Leave")
		mark_attendance(self.employee)
		mark_attendance(self.employee, date=add_days(today(), -1))
		frappe.set_user(self.employee.user_id)

	def cleanup(self):
		frappe.set_user("Administrator")
		frappe.conf.enable_comp_off_self_service = self.previous_flag
		frappe.local.comp_off_operation = None

	def create(self, date=None, **kwargs):
		return comp_off.create_request(date or today(), "Inventory work on holiday", **kwargs)

	def approve(self, request):
		frappe.set_user(self.manager.user_id)
		return comp_off.decide_request(request["name"], "Approved")

	def test_credit_and_retry_are_exactly_once(self):
		request = self.create()
		self.assertEqual(self.create()["name"], request["name"])
		self.assertEqual(request["status"], "Pending")
		self.assertFalse(request["leave_allocation"])
		approved = self.approve(request)
		self.assertEqual(approved["status"], "Approved")
		self.assertEqual(comp_off.decide_request(request["name"], "Approved"), approved)
		entries = frappe.get_all(
			"Leave Ledger Entry",
			filters={"transaction_name": approved["leave_allocation"]},
			fields=["leaves"],
		)
		self.assertEqual(sum(row.leaves for row in entries), 1)
		self.assertEqual(len(entries), 1)

	def test_only_current_manager_can_approve(self):
		request = self.create()
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")
		frappe.set_user(self.other.user_id)
		self.assertEqual(comp_off.get_requests(), [])
		self.assertEqual(comp_off.get_requests(team=1), [])
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")
		frappe.set_user("Administrator")
		self.employee.db_set("reports_to", self.other.name)
		frappe.set_user(self.manager.user_id)
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")
		frappe.set_user(self.other.user_id)
		self.assertEqual(len(comp_off.get_requests(team=1)), 1)
		self.assertEqual(comp_off.decide_request(request["name"], "Approved")["status"], "Approved")

	def test_generic_save_submit_and_marker_removal_are_blocked(self):
		request = self.create()
		frappe.set_user("Administrator")
		doc = frappe.get_doc(comp_off.DOCTYPE, request["name"])
		doc.portal_request = 0
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)
		frappe.conf.enable_comp_off_self_service = 0
		doc.reload()
		doc.portal_request = 0
		with self.assertRaises(frappe.PermissionError):
			doc.submit()
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc(comp_off.DOCTYPE, request["name"], ignore_permissions=True)

	def test_rejection_has_no_credit_and_can_be_reapplied(self):
		request = self.create()
		frappe.set_user(self.manager.user_id)
		with self.assertRaises(frappe.ValidationError):
			comp_off.decide_request(request["name"], "Rejected")
		rejected = comp_off.decide_request(request["name"], "Rejected", "Work not authorised")
		self.assertEqual(rejected["status"], "Rejected")
		self.assertFalse(rejected["leave_allocation"])
		self.assertEqual(
			comp_off.decide_request(request["name"], "Rejected", "Work not authorised"), rejected
		)
		with self.assertRaises(frappe.ValidationError):
			comp_off.decide_request(request["name"], "Approved")
		frappe.set_user(self.employee.user_id)
		self.assertNotEqual(self.create()["name"], rejected["name"])

	def test_full_day_cannot_be_requested_from_half_day_attendance(self):
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"Attendance",
			{"employee": self.employee.name, "attendance_date": today()},
			{"status": "Half Day", "half_day_status": "Absent"},
		)
		frappe.set_user(self.employee.user_id)
		with self.assertRaises(frappe.ValidationError):
			self.create()
		request = self.create(half_day=1)
		approved = self.approve(request)
		self.assertEqual(
			frappe.db.get_value("Leave Allocation", approved["leave_allocation"], "total_leaves_allocated"),
			0.5,
		)

	def test_attendance_is_revalidated_before_credit(self):
		request = self.create()
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"Attendance", {"employee": self.employee.name, "attendance_date": today()}, "docstatus", 2
		)
		frappe.set_user(self.manager.user_id)
		with self.assertRaises(frappe.ValidationError):
			comp_off.decide_request(request["name"], "Approved")
		self.assertFalse(frappe.db.get_value(comp_off.DOCTYPE, request["name"], "leave_allocation"))
		# Rejection remains available when attendance was corrected/cancelled.
		self.assertEqual(
			comp_off.decide_request(request["name"], "Rejected", "Attendance needs correction")["status"],
			"Rejected",
		)

	def test_out_of_order_credit_preserves_dates(self):
		later = self.create()
		earlier = self.create(add_days(today(), -1))
		self.approve(later)
		approved = self.approve(earlier)
		entries = frappe.get_all(
			"Leave Ledger Entry",
			filters={"transaction_name": approved["leave_allocation"]},
			fields=["leaves", "from_date"],
			order_by="from_date",
		)
		self.assertEqual(len(entries), 2)
		self.assertEqual(
			[getdate(row.from_date) for row in entries], [getdate(today()), getdate(add_days(today(), 1))]
		)
		self.assertEqual(get_leave_balance_on(self.employee.name, comp_off.LEAVE_TYPE, today()), 1)
		self.assertEqual(
			get_leave_balance_on(self.employee.name, comp_off.LEAVE_TYPE, add_days(today(), 1)), 2
		)

	def test_permission_hook_signature_and_disabled_native_compatibility(self):
		request = self.create()
		doc = frappe.get_doc(comp_off.DOCTYPE, request["name"])
		self.assertTrue(comp_off.has_permission(doc, ptype="read", user=self.employee.user_id, debug=False))
		self.assertFalse(comp_off.has_permission(doc, ptype="read", user=self.other.user_id, debug=False))
		self.assertFalse(comp_off.has_permission(doc, ptype="submit", user=self.manager.user_id, debug=False))
		frappe.conf.enable_comp_off_self_service = 0
		native_doc = frappe.new_doc(comp_off.DOCTYPE)
		self.assertTrue(
			comp_off.has_permission(native_doc, ptype="write", user=self.employee.user_id, debug=False)
		)

	def test_manager_missing_and_future_dates_fail(self):
		with self.assertRaises(frappe.ValidationError):
			self.create(add_days(today(), 1))
		frappe.set_user("Administrator")
		self.employee.db_set("reports_to", self.employee.name)
		frappe.set_user(self.employee.user_id)
		self.assertIsNone(comp_off.get_context()["manager"])
		with self.assertRaises(frappe.ValidationError):
			self.create()

	@skipUnless(
		os.environ.get("GITHUB_ACTIONS") == "true"
		and os.environ.get("HRMS_CONCURRENCY_ACCEPTANCE") == "1",
		"Separate CI-only concurrent transaction acceptance",
	)
	def test_concurrent_requests_and_approvals_are_exactly_once(self):
		result = _run_concurrency_acceptance(self)
		self.assertEqual(result["result"], "PASS")


def _run_concurrency_acceptance(case):
	"""Four independent DB connections; ONLY the disposable GitHub CI test site.

	Fixtures intentionally commit so real competing transactions can see them.
	The entire CI database is ephemeral; never run this on a Cloud site.
	"""
	from concurrent.futures import ThreadPoolExecutor
	from threading import Barrier

	if frappe.local.site != "test_site" or os.environ.get("GITHUB_ACTIONS") != "true":
		raise RuntimeError("Concurrency fixture is restricted to disposable GitHub CI")
	frappe.db.commit()  # nosemgrep: disposable CI fixture visibility between connections
	site = frappe.local.site
	sites_path = frappe.local.sites_path
	employee_user = case.employee.user_id
	manager_user = case.manager.user_id

	def parallel(tasks):
		barrier = Barrier(len(tasks))

		def worker(task):
			# MariaDB can abort a stale snapshot after waiting for the employee lock.
			# Retry at the simulated HTTP boundary, never inside the endpoint.
			for attempt in range(4):
				frappe.init(site=site, sites_path=sites_path)
				frappe.connect()
				try:
					frappe.flags.in_test = True
					frappe.conf.enable_comp_off_self_service = 1
					frappe.set_user(employee_user if task[0] == "create" else manager_user)
					if attempt == 0:
						barrier.wait(timeout=30)
					if task[0] == "create":
						result = comp_off.create_request(today(), "Concurrent holiday work")
					else:
						result = comp_off.decide_request(task[1], "Approved")
					frappe.db.commit()  # nosemgrep: simulate separate successful HTTP transactions
					return result
				except frappe.QueryDeadlockError:
					frappe.db.rollback()
					if attempt == 3:
						raise
				finally:
					frappe.destroy()

		with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
			return list(pool.map(worker, tasks))

	created = parallel([("create", None), ("create", None)])
	assert created[0]["name"] == created[1]["name"], "Concurrent create double request"
	frappe.db.rollback()
	frappe.set_user(employee_user)
	earlier = comp_off.create_request(str(add_days(today(), -1)), "Earlier holiday work")
	frappe.db.commit()  # nosemgrep: make second work date visible to competing reviewers
	decisions = parallel(
		[
			("approve", created[0]["name"]),
			("approve", created[0]["name"]),
			("approve", earlier["name"]),
			("approve", earlier["name"]),
		]
	)
	frappe.db.rollback()
	allocations = {r["leave_allocation"] for r in decisions}
	assert len(allocations) == 1, "Concurrent approvals created overlapping allocations"
	rows = frappe.get_all(
		"Leave Ledger Entry",
		filters={"transaction_name": next(iter(allocations))},
		fields=["leaves", "from_date"],
	)
	assert len(rows) == 2 and sum(row.leaves for row in rows) == 2, (
		"Concurrent approvals duplicated/lost credit"
	)
	assert {getdate(row.from_date) for row in rows} == {getdate(today()), getdate(add_days(today(), 1))}
	return {
		"concurrent_create_requests": 2,
		"unique_request": 1,
		"concurrent_approval_attempts": 4,
		"unique_allocations": 1,
		"ledger_entries": 2,
		"credited_days": 2,
		"result": "PASS",
	}
