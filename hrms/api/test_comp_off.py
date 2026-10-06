"""Native Frappe integration coverage for the optional employee credit workflow."""

import os
from unittest import skipUnless
from unittest.mock import patch

import frappe
from frappe.exceptions import FrappeTypeError
from frappe.model.document import Document
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
from hrms.setup import create_comp_off_approver_role
from hrms.tests.utils import HRMSTestSuite


class TestCompOffPortal(HRMSTestSuite):
	def setUp(self):
		frappe.set_user("Administrator")
		self.previous_flag = frappe.conf.get("enable_comp_off_self_service")
		self.previous_maintenance = frappe.conf.get("maintenance_mode")
		self.previous_scheduler = frappe.conf.get("pause_scheduler")
		frappe.conf.enable_comp_off_self_service = 1
		self.addCleanup(self.cleanup)
		identity_suffix = frappe.generate_hash(length=10)
		for key in ("employee", "manager", "other"):
			email = f"comp-off-{key}-{identity_suffix}@example.com"
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
		frappe.set_user(self.employee.user_id)

	def cleanup(self):
		frappe.set_user("Administrator")
		frappe.conf.enable_comp_off_self_service = self.previous_flag
		frappe.conf.maintenance_mode = self.previous_maintenance
		frappe.conf.pause_scheduler = self.previous_scheduler
		frappe.local.comp_off_operation = None

	def create(self, date=None, **kwargs):
		return comp_off.create_request(date or today(), "Inventory work on holiday", **kwargs)

	def approve(self, request):
		frappe.set_user(self.manager.user_id)
		return comp_off.decide_request(request["name"], "Approved")

	def enable_recovery_controls(self):
		frappe.set_user("Administrator")
		frappe.conf.maintenance_mode = 1
		frappe.conf.pause_scheduler = 1

	def approved_credit(self, half_day=False):
		request = self.create(half_day=half_day)
		return request, self.approve(request)

	def recovery_snapshot(self, request):
		allocation = frappe.get_doc("Leave Allocation", request["leave_allocation"])
		return {
			"docstatus": frappe.db.get_value(comp_off.DOCTYPE, request["name"], "docstatus"),
			"allocation_total": allocation.total_leaves_allocated,
			"ledger_count": frappe.db.count(
				"Leave Ledger Entry", {"transaction_name": allocation.name, "docstatus": 1}
			),
			"ledger_sum": sum(
				frappe.get_all(
					"Leave Ledger Entry",
					filters={"transaction_name": allocation.name, "docstatus": 1},
					pluck="leaves",
				)
			),
			"comments": frappe.db.count(
				"Comment",
				{
					"reference_doctype": comp_off.DOCTYPE,
					"reference_name": request["name"],
					"content": ["like", "%comp_off_recovery_v1%"],
				},
			),
		}

	def test_credit_and_retry_are_exactly_once(self):
		self.assertFalse(frappe.db.exists("Attendance", {"employee": self.employee.name}))
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

	def grant_company_approver(self, employee=None):
		frappe.set_user("Administrator")
		create_comp_off_approver_role()
		frappe.get_doc("User", (employee or self.other).user_id).add_roles(comp_off.APPROVER_ROLE)
		frappe.set_user((employee or self.other).user_id)

	def test_company_approver_queue_decision_and_retry(self):
		request = self.create(half_day=1)
		self.grant_company_approver()
		context = comp_off.get_context()
		self.assertFalse(context["is_manager"])
		self.assertTrue(context["is_company_approver"])
		self.assertEqual(comp_off.get_requests(), [])
		queue = comp_off.get_requests(team=1)
		self.assertEqual([row["name"] for row in queue], [request["name"]])
		self.assertTrue(queue[0]["can_approve"])
		approved = comp_off.decide_request(request["name"], "Approved", "Holiday work verified")
		self.assertEqual(approved["decision_by"], self.other.user_id)
		self.assertEqual(approved["decision_reason"], "Holiday work verified")
		self.assertEqual(comp_off.decide_request(request["name"], "Approved"), approved)
		entries = frappe.get_all(
			"Leave Ledger Entry",
			filters={"transaction_name": approved["leave_allocation"], "docstatus": 1},
			pluck="leaves",
		)
		self.assertEqual(entries, [0.5])

	def test_company_approver_cannot_approve_self_or_use_desk(self):
		request = self.create()
		self.grant_company_approver(self.employee)
		self.assertEqual(comp_off.get_requests(team=1), [])
		self.assertFalse(comp_off.get_requests()[0]["can_approve"])
		for decision in ("Approved", "Rejected"):
			with self.assertRaises(frappe.PermissionError):
				comp_off.decide_request(request["name"], decision, "Not allowed")
		self.grant_company_approver()
		doc = frappe.get_doc(comp_off.DOCTYPE, request["name"])
		for permission in ("write", "submit", "cancel", "delete"):
			self.assertFalse(comp_off.has_permission(doc, ptype=permission))
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			doc.submit()

	def test_company_approver_requires_same_company_active_unique_identity(self):
		request = self.create()
		self.grant_company_approver()
		for field, value in (("company", "_Test Company 2"), ("status", "Inactive")):
			original = self.other.get(field)
			frappe.db.set_value("Employee", self.other.name, field, value)
			with self.assertRaises(frappe.PermissionError):
				comp_off.decide_request(request["name"], "Approved")
			frappe.db.set_value("Employee", self.other.name, field, original)
		# Simulate corrupt duplicate mappings without relaxing native Employee validation.
		frappe.set_user("Administrator")
		duplicate = frappe.copy_doc(self.other)
		duplicate.user_id = None
		duplicate.insert()
		frappe.db.set_value("Employee", duplicate.name, "user_id", self.other.user_id)
		frappe.set_user(self.other.user_id)
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")
		frappe.db.set_value("Employee", duplicate.name, "user_id", None)
		# Cross-company requests must not be disclosed by the company-wide queue.
		frappe.db.set_value("Employee", self.employee.name, "company", "_Test Company 2")
		self.assertEqual(comp_off.get_requests(team=1), [])
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")

	def test_company_approver_revocation_and_disabled_controls(self):
		request = self.create()
		self.grant_company_approver()
		# Prime ordinary roles cache, then revoke the persisted grant directly.
		frappe.get_roles(self.other.user_id)
		frappe.db.delete("Has Role", {"parent": self.other.user_id, "role": comp_off.APPROVER_ROLE})
		self.assertFalse(comp_off.get_context()["is_company_approver"])
		self.assertEqual(comp_off.get_requests(team=1), [])
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")
		self.grant_company_approver()
		frappe.db.set_value("Role", comp_off.APPROVER_ROLE, "disabled", 1)
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")
		frappe.db.set_value("Role", comp_off.APPROVER_ROLE, "disabled", 0)
		frappe.db.set_value("User", self.other.user_id, "enabled", 0)
		with self.assertRaises(frappe.PermissionError):
			comp_off.get_requests(team=1)
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")

	def test_company_approver_rechecked_after_lock(self):
		request = self.create()
		self.grant_company_approver()
		lock = comp_off._lock_employee

		def revoke_after_lock(employee):
			lock(employee)
			frappe.db.delete("Has Role", {"parent": self.other.user_id, "role": comp_off.APPROVER_ROLE})

		with patch.object(comp_off, "_lock_employee", side_effect=revoke_after_lock):
			with self.assertRaises(frappe.PermissionError):
				comp_off.decide_request(request["name"], "Approved")
		self.assertEqual(frappe.db.get_value(comp_off.DOCTYPE, request["name"], "portal_status"), "Pending")

	def test_company_approver_rejection_and_feature_off(self):
		request = self.create()
		self.grant_company_approver()
		with self.assertRaises(frappe.ValidationError):
			comp_off.decide_request(request["name"], "Rejected")
		rejected = comp_off.decide_request(request["name"], "Rejected", "Work not verified")
		self.assertEqual(rejected["decision_by"], self.other.user_id)
		self.assertFalse(rejected["leave_allocation"])
		self.assertEqual(comp_off.decide_request(request["name"], "Rejected", "Work not verified"), rejected)
		frappe.conf.enable_comp_off_self_service = 0
		with self.assertRaises(frappe.ValidationError):
			comp_off.decide_request(request["name"], "Rejected", "Work not verified")

	def test_company_approver_role_provisioning_never_assigns_users(self):
		frappe.set_user("Administrator")
		before = frappe.db.count("Has Role", {"role": comp_off.APPROVER_ROLE})
		create_comp_off_approver_role()
		create_comp_off_approver_role()
		self.assertEqual(frappe.db.count("Has Role", {"role": comp_off.APPROVER_ROLE}), before)
		self.assertEqual(frappe.db.get_value("Role", comp_off.APPROVER_ROLE, "desk_access"), 0)
		profile = frappe.get_doc("Role Profile", comp_off.APPROVER_ROLE)
		self.assertEqual([row.role for row in profile.roles], [comp_off.APPROVER_ROLE])
		self.assertIsNone(comp_off._company_approver())

	def test_hr_roles_alone_do_not_grant_company_approval(self):
		request = self.create()
		frappe.set_user("Administrator")
		frappe.get_doc("User", self.other.user_id).add_roles("HR Manager", "HR User", "Leave Approver")
		frappe.set_user(self.other.user_id)
		self.assertFalse(comp_off.get_context()["is_company_approver"])
		self.assertEqual(comp_off.get_requests(team=1), [])
		with self.assertRaises(frappe.PermissionError):
			comp_off.decide_request(request["name"], "Approved")

	def test_role_provisioning_rejects_conflicting_metadata(self):
		frappe.set_user("Administrator")
		create_comp_off_approver_role()
		frappe.db.set_value("Role", comp_off.APPROVER_ROLE, "desk_access", 1)
		with self.assertRaises(frappe.ValidationError):
			create_comp_off_approver_role()
		frappe.db.set_value("Role", comp_off.APPROVER_ROLE, "desk_access", 0)
		profile = frappe.get_doc("Role Profile", comp_off.APPROVER_ROLE)
		profile.append("roles", {"role": "HR Manager"})
		profile.save()
		with self.assertRaises(frappe.ValidationError):
			create_comp_off_approver_role()

	def test_additive_profile_grant_survives_user_save(self):
		request = self.create()
		frappe.set_user("Administrator")
		create_comp_off_approver_role()
		profile = frappe.get_doc(
			{
				"doctype": "Role Profile",
				"role_profile": "_Test Existing Comp Off Profile",
				"roles": [{"role": "Employee"}],
			}
		).insert()
		user = frappe.get_doc("User", self.other.user_id)
		user.append("role_profiles", {"role_profile": profile.name})
		user.save()
		before_roles = {row.role for row in user.roles}
		user.append("role_profiles", {"role_profile": comp_off.APPROVER_ROLE})
		user.save()
		user.reload()
		self.assertEqual({row.role for row in user.roles}, before_roles | {comp_off.APPROVER_ROLE})
		self.assertEqual(
			{row.role_profile for row in user.role_profiles}, {profile.name, comp_off.APPROVER_ROLE}
		)
		user.save()
		frappe.set_user(self.other.user_id)
		self.assertTrue(comp_off.get_requests(team=1)[0]["can_approve"])
		self.assertEqual(comp_off.decide_request(request["name"], "Approved")["status"], "Approved")

	def test_enabled_native_hr_compatibility_keeps_portal_records_protected(self):
		native_doc = frappe.new_doc(comp_off.DOCTYPE)
		self.assertTrue(comp_off.has_permission(native_doc, ptype="write", user="Administrator", debug=False))
		self.assertFalse(
			comp_off.has_permission(native_doc, ptype="write", user=self.employee.user_id, debug=False)
		)
		request = self.create()
		portal_doc = frappe.get_doc(comp_off.DOCTYPE, request["name"])
		self.assertFalse(
			comp_off.has_permission(portal_doc, ptype="write", user="Administrator", debug=False)
		)
		self.assertNotIn(comp_off.reverse_unused_portal_credit, frappe.whitelisted)

	def test_native_hr_roles_keep_only_their_existing_document_permissions(self):
		request = self.create()
		portal_doc = frappe.get_doc(comp_off.DOCTYPE, request["name"])
		for role in ("HR Manager", "HR User", "System Manager"):
			frappe.set_user("Administrator")
			email = f"comp-off-{role.lower().replace(' ', '-')}@example.com"
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": role,
					"send_welcome_email": 0,
					"roles": [{"role": role}],
				}
			).insert()
			frappe.set_user(user.name)
			native_doc = frappe.new_doc(comp_off.DOCTYPE)
			with self.subTest(role=role):
				comp_off.guard_write(native_doc)
				for permission in ("create", "write", "submit", "cancel"):
					frappe.conf.enable_comp_off_self_service = 0
					before = frappe.has_permission(comp_off.DOCTYPE, permission, doc=native_doc)
					frappe.conf.enable_comp_off_self_service = 1
					self.assertEqual(
						frappe.has_permission(comp_off.DOCTYPE, permission, doc=native_doc), before
					)
				self.assertTrue(frappe.has_permission(comp_off.DOCTYPE, "write", doc=native_doc))
				self.assertFalse(comp_off.has_permission(portal_doc, ptype="write"))
				with self.assertRaises(frappe.PermissionError):
					comp_off.guard_write(portal_doc)
		frappe.set_user(self.employee.user_id)
		with self.assertRaises(frappe.PermissionError):
			comp_off.guard_write(frappe.new_doc(comp_off.DOCTYPE))

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

	def test_recovery_cancels_a_clean_full_day_credit_once_with_audit(self):
		request, approved = self.approved_credit()
		self.enable_recovery_controls()
		before = self.recovery_snapshot(approved)

		recovered = comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
		self.assertEqual(
			recovered,
			{
				"name": request["name"],
				"status": "Cancelled",
				"leave_allocation": approved["leave_allocation"],
			},
		)
		doc = frappe.get_doc(comp_off.DOCTYPE, request["name"])
		allocation = frappe.get_doc("Leave Allocation", approved["leave_allocation"])
		self.assertEqual((doc.docstatus, doc.portal_status), (2, "Approved"))
		self.assertEqual(allocation.total_leaves_allocated, 0)
		after = self.recovery_snapshot(approved)
		self.assertEqual(after["ledger_count"], before["ledger_count"] + 1)
		self.assertEqual(after["ledger_sum"], 0)
		self.assertEqual(after["comments"], before["comments"] + 1)
		self.assertEqual(
			frappe.get_value(
				"Leave Ledger Entry",
				{"transaction_name": allocation.name, "leaves": -1, "docstatus": 1},
				["from_date", "to_date"],
				as_dict=True,
			),
			frappe._dict(
				{"from_date": getdate(add_days(today(), 1)), "to_date": getdate(allocation.to_date)}
			),
		)
		self.assertEqual(
			comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval"), recovered
		)
		self.assertEqual(self.recovery_snapshot(approved), after)

	def test_recovery_cancels_a_clean_half_day_credit(self):
		request, approved = self.approved_credit(half_day=True)
		self.enable_recovery_controls()
		recovered = comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
		allocation = frappe.get_doc("Leave Allocation", approved["leave_allocation"])
		self.assertEqual(recovered["status"], "Cancelled")
		self.assertEqual(allocation.total_leaves_allocated, 0)
		self.assertEqual(
			frappe.db.get_value(
				"Leave Ledger Entry", {"transaction_name": allocation.name, "leaves": -0.5}, "leaves"
			),
			-0.5,
		)

	def test_recovery_requires_authorised_user_reason_and_operational_controls(self):
		request, approved = self.approved_credit()
		before = self.recovery_snapshot(approved)
		frappe.set_user(self.manager.user_id)
		frappe.conf.maintenance_mode = 1
		frappe.conf.pause_scheduler = 1
		with self.assertRaises(frappe.PermissionError):
			comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
		self.enable_recovery_controls()
		with self.assertRaises(frappe.ValidationError):
			comp_off.reverse_unused_portal_credit(request["name"], "")
		frappe.conf.maintenance_mode = 0
		with self.assertRaises(frappe.PermissionError):
			comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
		frappe.conf.maintenance_mode = 1
		frappe.conf.pause_scheduler = 0
		with self.assertRaises(frappe.PermissionError):
			comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
		self.assertEqual(self.recovery_snapshot(approved), before)

	def test_recovery_refuses_pending_or_approved_leave_use_without_mutation(self):
		request, approved = self.approved_credit()
		self.enable_recovery_controls()
		allocation = frappe.get_doc("Leave Allocation", approved["leave_allocation"])
		for status, submit in (("Open", False), ("Approved", True)):
			application = frappe.get_doc(
				{
					"doctype": "Leave Application",
					"employee": self.employee.name,
					"leave_type": comp_off.LEAVE_TYPE,
					"from_date": allocation.from_date,
					"to_date": allocation.from_date,
					"company": self.employee.company,
					"status": status,
					"leave_approver": "Administrator",
				}
			).insert()
			if submit:
				application.submit()
			before = self.recovery_snapshot(approved)
			with self.subTest(status=status), self.assertRaises(frappe.ValidationError):
				comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
			self.assertEqual(self.recovery_snapshot(approved), before)
			if submit:
				application.cancel()
			else:
				frappe.delete_doc("Leave Application", application.name)

	def test_recovery_refuses_negative_ledger_or_carry_forward_allocation_without_mutation(self):
		request, approved = self.approved_credit()
		self.enable_recovery_controls()
		before = self.recovery_snapshot(approved)
		allocation = frappe.get_doc("Leave Allocation", approved["leave_allocation"])
		frappe.db.savepoint("negative_ledger_fixture")
		negative_entry = frappe.get_doc(
			{
				"doctype": "Leave Ledger Entry",
				"employee": self.employee.name,
				"leave_type": comp_off.LEAVE_TYPE,
				"transaction_type": "Leave Allocation",
				"transaction_name": allocation.name,
				"leaves": -0.5,
				"from_date": allocation.from_date,
				"to_date": allocation.to_date,
				"company": self.employee.company,
			}
		).insert()
		negative_entry.submit()
		with self.assertRaises(frappe.ValidationError):
			comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
		self.assertEqual(
			self.recovery_snapshot(approved),
			before | {"ledger_count": before["ledger_count"] + 1, "ledger_sum": before["ledger_sum"] - 0.5},
		)
		frappe.db.rollback(save_point="negative_ledger_fixture")
		frappe.db.set_value("Leave Allocation", allocation.name, "carry_forward", 1)
		before_carry_forward = self.recovery_snapshot(approved)
		with self.assertRaises(frappe.ValidationError):
			comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
		self.assertEqual(self.recovery_snapshot(approved), before_carry_forward)

	def test_recovery_rolls_back_when_audit_comment_fails(self):
		request, approved = self.approved_credit()
		self.enable_recovery_controls()
		before = self.recovery_snapshot(approved)
		with patch.object(Document, "add_comment", side_effect=RuntimeError("audit write failed")):
			with self.assertRaisesRegex(RuntimeError, "audit write failed"):
				comp_off.reverse_unused_portal_credit(request["name"], "Duplicate approval")
		self.assertEqual(self.recovery_snapshot(approved), before)

	def test_half_day_without_attendance_requires_approval_and_credits_half_day(self):
		self.assertFalse(frappe.db.exists("Attendance", {"employee": self.employee.name}))
		request = self.create(half_day=1)
		self.assertEqual(request["status"], "Pending")
		self.assertFalse(request["leave_allocation"])
		self.assertEqual(self.create(half_day=1)["name"], request["name"])
		with self.assertRaises(frappe.ValidationError):
			self.create(half_day=0)
		approved = self.approve(request)
		self.assertEqual(
			frappe.db.get_value("Leave Allocation", approved["leave_allocation"], "total_leaves_allocated"),
			0.5,
		)
		self.assertFalse(frappe.db.exists("Attendance", {"employee": self.employee.name}))

	def test_attendance_does_not_control_request_or_approval(self):
		frappe.set_user("Administrator")
		mark_attendance(self.employee, status="Half Day", half_day_status="Absent")
		frappe.set_user(self.employee.user_id)
		request = self.create(half_day=0)
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"Attendance", {"employee": self.employee.name, "attendance_date": today()}, "docstatus", 2
		)
		approved = self.approve(request)
		self.assertEqual(approved["status"], "Approved")
		self.assertEqual(
			frappe.db.get_value("Leave Allocation", approved["leave_allocation"], "total_leaves_allocated"),
			1,
		)

	def test_calendar_dates_without_attendance_exclude_claimed_and_pre_joining_days(self):
		self.assertFalse(frappe.db.exists("Attendance", {"employee": self.employee.name}))
		self.assertEqual(
			comp_off.get_context()["eligible_dates"],
			[{"date": today()}, {"date": add_days(today(), -1)}],
		)
		request = self.create()
		self.assertEqual(comp_off.get_context()["eligible_dates"], [{"date": add_days(today(), -1)}])
		frappe.set_user(self.manager.user_id)
		comp_off.decide_request(request["name"], "Rejected", "Work not authorised")
		frappe.set_user("Administrator")
		self.employee.db_set("date_of_joining", today())
		frappe.set_user(self.employee.user_id)
		self.assertEqual(comp_off.get_context()["eligible_dates"], [{"date": today()}])
		with self.assertRaises(frappe.ValidationError):
			self.create(add_days(today(), -1))

	def test_non_holiday_and_invalid_duration_remain_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			self.create(add_days(today(), -2))
		for half_day, error in (
			(-1, frappe.ValidationError),
			(2, frappe.ValidationError),
			("0.5", FrappeTypeError),
			("invalid", FrappeTypeError),
		):
			with self.subTest(half_day=half_day), self.assertRaises(error):
				self.create(half_day=half_day)
		self.assertFalse(frappe.db.exists(comp_off.DOCTYPE, {"employee": self.employee.name}))

	def test_calendar_dates_require_leave_period_for_next_day_credit(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("Leave Period", {"company": "_Test Company", "is_active": 1}, "to_date", today())
		frappe.set_user(self.employee.user_id)
		self.assertEqual(comp_off.get_context()["eligible_dates"], [{"date": add_days(today(), -1)}])
		with self.assertRaises(frappe.ValidationError):
			self.create()
		self.assertEqual(self.create(add_days(today(), -1))["status"], "Pending")

	def test_duration_accepts_json_boolean_and_form_integer(self):
		for half_day in (True, 1, "1"):
			with self.subTest(half_day=half_day):
				request = self.create(half_day=half_day)
				self.assertEqual(request["half_day"], 1)
		for half_day in (False, 0, "0"):
			with self.subTest(half_day=half_day):
				request = self.create(add_days(today(), -1), half_day=half_day)
				self.assertEqual(request["half_day"], 0)

	def test_joining_date_is_revalidated_before_credit(self):
		request = self.create(add_days(today(), -1))
		frappe.set_user("Administrator")
		self.employee.db_set("date_of_joining", today())
		with self.assertRaises(frappe.ValidationError):
			self.approve(request)
		self.assertFalse(frappe.db.get_value(comp_off.DOCTYPE, request["name"], "leave_allocation"))

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
		os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("HRMS_CONCURRENCY_ACCEPTANCE") == "1",
		"Separate CI-only concurrent transaction acceptance",
	)
	def test_concurrent_requests_and_approvals_are_exactly_once(self):
		result = _run_concurrency_acceptance(self)
		self.assertEqual(result["result"], "PASS")

	@skipUnless(
		os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("HRMS_CONCURRENCY_ACCEPTANCE") == "1",
		"Separate CI-only concurrent transaction acceptance",
	)
	def test_manager_and_company_approver_race_credits_once(self):
		self.grant_company_approver()
		result = _run_concurrency_acceptance(self, company_approver=self.other.user_id)
		self.assertEqual(result["result"], "PASS")


def _run_concurrency_acceptance(case, company_approver=None):
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
					frappe.set_user(
						employee_user if task[0] == "create" else (task[2] if len(task) > 2 else manager_user)
					)
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
			("approve", created[0]["name"], company_approver or manager_user),
			("approve", created[0]["name"]),
			("approve", earlier["name"], company_approver or manager_user),
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
