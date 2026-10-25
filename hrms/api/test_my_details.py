"""Native integration coverage for the session-bound My Details workflow.

These tests deliberately exercise permissions and persistence boundaries rather
than duplicating implementation details.  Every identity is synthetic and no
mail, scheduler, or external endpoint is used.
"""

import io
import json
import os
from unittest import skipUnless
from unittest.mock import patch

from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from hrms.api import my_details
from hrms.patches.v16_0.create_my_details_fields import execute as setup_my_details_fields
from hrms.tests.utils import HRMSTestSuite


class TestMyDetails(HRMSTestSuite):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# This is intentionally the clean-install contract: the patch must be safe
		# on a site with no legacy aliases, and the suite then supplies aliases which
		# vary between supported HRMS versions.
		setup_my_details_fields()
		meta = frappe.get_meta("Employee")
		aliases = [
			("custom_pan_number", "PAN Number", "Data"),
			("custom_ifsc_code", "IFSC Code", "Data"),
			("custom_uan", "UAN", "Data"),
			("custom_esi_no", "ESI IP Number", "Data"),
		]
		missing = [
			{"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "insert_after": "bank_ac_no"}
			for fieldname, label, fieldtype in aliases
			if not meta.has_field(fieldname)
		]
		if missing:
			create_custom_fields({"Employee": missing}, update=False)
			frappe.clear_cache(doctype="Employee")

	def setUp(self):
		frappe.set_user("Administrator")
		self.previous_flag = frappe.conf.get("enable_employee_my_details")
		frappe.conf.enable_employee_my_details = 1
		self.addCleanup(self.cleanup)
		self.ident = frappe.generate_hash(length=10)
		self.employee = self.make_employee("employee")
		self.other = self.make_employee("other")
		self.reviewer = self.make_employee("reviewer", role="HR Manager")
		self.set_value(self.employee, "city", "Old City")
		self.set_value(self.other, "city", "Other City")
		self.set_value(self.employee, "pan", "ABCDE1234F")
		self.set_value(self.other, "pan", "ZZZZZ9999Z")
		frappe.set_user(self.employee.user_id)

	def cleanup(self):
		frappe.set_user("Administrator")
		frappe.conf.enable_employee_my_details = self.previous_flag
		frappe.local.my_details_operation = None

	def make_employee(self, label, role="Employee"):
		email = f"my-details-{self.ident}-{label}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"My Details {label}",
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"My Details {label}",
				"company": "_Test Company",
				"status": "Active",
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": "2020-01-01",
				"user_id": user.name,
				"create_user_permission": 0,
			}
		).insert(ignore_permissions=True)

	def target(self, key):
		return my_details._fields()[key]["targets"][0]

	def set_value(self, employee, key, value):
		field = self.target(key)
		employee.db_set(field, value)
		return field

	def value(self, employee, key):
		return frappe.db.get_value("Employee", employee.name, self.target(key))

	def context(self):
		return my_details.get_context()

	def begin(self, changes, request_id=None, retry_of=""):
		return my_details.begin_request(
			changes,
			self.context()["version"],
			request_id or f"request-{frappe.generate_hash(length=20)}",
			retry_of,
		)

	def pdf(self):
		writer = PdfWriter()
		writer.add_blank_page(width=200, height=200)
		output = io.BytesIO()
		writer.write(output)
		return output.getvalue()

	def add_proof(self, request, kind):
		doc = frappe.get_doc(my_details.DOCTYPE, request["name"])
		return my_details._store_proof(doc, kind, self.pdf(), f"{kind}.pdf")

	def upload_file(self, request, kind, content=None, filename=None):
		storage = FileStorage(
			stream=io.BytesIO(content if content is not None else self.pdf()),
			filename=filename or f"{kind}.pdf",
			content_type="application/pdf",
		)
		fake_request = frappe._dict(files=frappe._dict(file=storage))
		with patch.object(frappe.local, "request", fake_request):
			return my_details.upload_proof(request["name"], kind)

	def submit(self, request):
		return my_details.submit_request(request["name"], consent=True)

	def review(self, request):
		frappe.set_user(self.reviewer.user_id)
		return my_details.review_request(request["name"])

	def test_clean_install_field_setup_exposes_required_personal_fields(self):
		setup_my_details_fields()
		fields = my_details._fields()
		for key in (
			"bank_holder",
			"aadhaar",
			"city",
			"state",
			"pin_code",
			"nominee_name",
			"nominee_relation",
			"nominee_dob",
		):
			with self.subTest(key=key):
				self.assertIn(key, fields)
				self.assertTrue(fields[key]["targets"])

	def test_session_is_bound_to_employee_for_context_reveal_requests_submit_and_download(self):
		request = self.begin({"city": "New City"})
		self.assertEqual(my_details.reveal_field("pan")["value"], "ABCDE1234F")
		frappe.set_user(self.other.user_id)
		context = self.context()
		self.assertEqual(context["employee_name"], self.other.employee_name)
		self.assertNotIn(request["name"], [row["name"] for row in context["requests"]])
		self.assertEqual(my_details.reveal_field("pan")["value"], "ZZZZZ9999Z")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(my_details.DOCTYPE, pluck="name")
		for call in (
			lambda: my_details.submit_request(request["name"], consent=True),
			lambda: my_details.download_proof(request["name"], "pan"),
			lambda: my_details.review_request(request["name"]),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_allowlist_masking_and_ascii_validation_do_not_leak_or_accept_untrusted_fields(self):
		context = self.context()
		pan = next(field for field in context["fields"] if field["key"] == "pan")
		self.assertEqual(pan["value"], "•••• 234F")
		self.assertNotIn("pan_number", {field["key"] for field in context["fields"]})
		profile = my_details.get_profile()
		self.assertNotIn("pan_number", profile["values"])
		self.assertNotIn("bank_ac_no", profile["values"])
		with self.assertRaises(frappe.ValidationError):
			self.begin({"user_id": "Administrator"})
		with self.assertRaises(frappe.ValidationError):
			self.begin({"pan": "ＡBCDE1234F"})
		with self.assertRaises(frappe.ValidationError):
			self.begin({"city": "Bad\x01City"})
		with self.assertRaises(frappe.PermissionError):
			my_details.reveal_field("city")
		with self.assertRaises(frappe.PermissionError):
			frappe.new_doc(my_details.DOCTYPE).insert(ignore_permissions=True)
		own_employee = frappe.get_doc("Employee", self.employee.name)
		own_employee.set(self.target("city"), "Generic Employee Write")
		with self.assertRaises(frappe.PermissionError):
			own_employee.save()

	def test_pending_request_never_changes_master_and_begin_submit_are_idempotent(self):
		request_id = "idempotent-" + frappe.generate_hash(length=20)
		request = self.begin({"city": "Pending City"}, request_id)
		self.assertEqual(self.begin({"city": "Pending City"}, request_id), request)
		with self.assertRaises(frappe.ValidationError):
			self.begin({"city": "Changed Payload"}, request_id)
		self.assertEqual(self.value(self.employee, "city"), "Old City")
		pending = self.submit(request)
		self.assertEqual(pending["status"], "Pending review")
		self.assertEqual(self.submit(request), pending)
		self.assertEqual(self.value(self.employee, "city"), "Old City")

	def test_hr_cannot_list_read_review_or_download_draft_or_withdrawn_requests(self):
		request = self.begin({"pan": "BBBBB1234B"})
		self.add_proof(request, "pan")

		def assert_hidden_from_hr():
			frappe.set_user(self.reviewer.user_id)
			doc = frappe.get_doc(my_details.DOCTYPE, request["name"])
			self.assertFalse(my_details.has_permission(doc, "read", self.reviewer.user_id))
			self.assertNotIn(
				request["name"],
				frappe.get_list(my_details.DOCTYPE, filters={"name": request["name"]}, pluck="name"),
			)
			with self.assertRaises(frappe.PermissionError):
				my_details.review_request(request["name"])
			with self.assertRaises(frappe.PermissionError):
				my_details.download_proof(request["name"], "pan")

		assert_hidden_from_hr()
		frappe.set_user(self.employee.user_id)
		self.assertEqual(my_details.discard_draft(request["name"])["status"], "Withdrawn")
		assert_hidden_from_hr()

	def test_inactive_duplicate_warns_and_requires_acknowledgement_but_does_not_block(self):
		self.other.db_set("status", "Inactive")
		request = self.begin({"pan": "ZZZZZ9999Z"})
		self.add_proof(request, "pan")
		self.submit(request)
		review = self.review(request)
		self.assertEqual(review["blockers"], [])
		self.assertTrue(any("inactive employee" in warning for warning in review["warnings"]))
		with self.assertRaises(frappe.ValidationError):
			my_details.decide_request(
				request["name"], "Approved", review["review_token"], ["pan"], "Verified"
			)
		approved = my_details.decide_request(
			request["name"],
			"Approved",
			review["review_token"],
			["pan"],
			"Verified",
			acknowledge_warnings=True,
		)
		self.assertEqual(approved["status"], "Approved")
		self.assertEqual(self.value(self.employee, "pan"), "ZZZZZ9999Z")

	def test_five_recent_historical_requests_enforce_24_hour_quota(self):
		for index in range(5):
			doc = frappe.get_doc(
				{
					"doctype": my_details.DOCTYPE,
					"name": f"EDC-QUOTA-{self.ident}-{index}",
					"employee": self.employee.name,
					"company": self.employee.company,
					"requested_by": self.employee.user_id,
					"status": "Withdrawn",
					"changes_json": json.dumps({"city": f"Quota City {index}"}),
					"baseline_json": json.dumps({self.target("city"): "Old City"}),
				}
			)
			my_details._save(doc, new=True)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.begin({"city": "Sixth City"})
		self.assertIn("recent request limit", str(caught.exception))

	def test_historical_result_keeps_labels_when_a_target_field_is_no_longer_in_metadata(self):
		request = self.begin({"city": "Historical City"})
		doc = frappe.get_doc(my_details.DOCTYPE, request["name"])
		fields = my_details._fields()
		fields["city"] = fields["city"] | {"targets": []}
		with patch.object(my_details, "_fields", return_value=fields):
			result = my_details._result(doc)
		self.assertEqual(result["changes"], [{"key": "city", "label": "City", "value": "Historical City"}])

	def test_upload_endpoint_rejects_missing_wrong_or_cross_employee_proofs(self):
		request = self.begin({"pan": "BBBBB1234B"})
		with self.assertRaises(frappe.ValidationError):
			self.submit(request)
		with self.assertRaises(frappe.PermissionError):
			self.upload_file(request, "bank")
		frappe.set_user(self.other.user_id)
		with self.assertRaises(frappe.PermissionError):
			self.upload_file(request, "pan")
		frappe.set_user(self.employee.user_id)
		self.assertEqual(self.upload_file(request, "pan"), {"kind": "pan", "saved": True})
		with self.assertRaises(frappe.ValidationError):
			self.upload_file(request, "pan", content=b"not a PDF", filename="pan.pdf")
		self.assertEqual(self.submit(request)["status"], "Pending review")

	def test_duplicate_identity_is_blocked_without_disclosing_other_employee_details(self):
		request = self.begin({"pan": "ZZZZZ9999Z"})
		self.add_proof(request, "pan")
		self.submit(request)
		review = self.review(request)
		self.assertTrue(any("PAN" in blocker for blocker in review["blockers"]))
		self.assertNotIn(self.other.name, " ".join(review["blockers"]))
		self.assertNotIn(self.other.employee_name, " ".join(review["blockers"]))
		with self.assertRaises(frappe.ValidationError) as caught:
			my_details.decide_request(
				request["name"], "Approved", review["review_token"], ["pan"], "Verified"
			)
		message = str(caught.exception)
		self.assertIn("already recorded", message)
		self.assertNotIn(self.other.name, message)
		self.assertNotIn(self.other.employee_name, message)
		self.assertEqual(self.value(self.employee, "pan"), "ABCDE1234F")

	def test_approval_and_correction_do_not_enqueue_mail(self):
		before = frappe.db.count("Email Queue")
		request = self.begin({"city": "No Mail City"})
		self.submit(request)
		review = self.review(request)
		my_details.decide_request(request["name"], "Approved", review["review_token"], ["city"], "Verified")
		self.assertEqual(frappe.db.count("Email Queue"), before)
		frappe.set_user(self.employee.user_id)
		correction = self.begin({"state": "No Mail State"})
		self.submit(correction)
		review = self.review(correction)
		my_details.decide_request(
			correction["name"], "Needs correction", review["review_token"], [], "Please clarify state"
		)
		self.assertEqual(frappe.db.count("Email Queue"), before)

	def test_guest_disabled_and_ambiguous_employee_mappings_are_denied(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			my_details.get_context()
		frappe.set_user(self.employee.user_id)
		frappe.db.set_value("User", self.employee.user_id, "enabled", 0)
		with self.assertRaises(frappe.PermissionError):
			my_details.get_context()
		frappe.db.set_value("User", self.employee.user_id, "enabled", 1)
		self.other.db_set("user_id", self.employee.user_id)
		with self.assertRaises(frappe.PermissionError):
			my_details.get_context()

	def test_proof_cannot_be_made_public_reparented_or_read_through_native_file_acl(self):
		request = self.begin({"pan": "BBBBB1234B"})
		self.add_proof(request, "pan")
		file = frappe.get_doc("File", frappe.get_value(my_details.DOCTYPE, request["name"], "pan_proof"))
		frappe.set_user("Administrator")
		file.is_private = 0
		with self.assertRaises(frappe.PermissionError):
			file.save(ignore_permissions=True)
		file.reload()
		file.attached_to_name = self.other.name
		with self.assertRaises(frappe.PermissionError):
			file.save(ignore_permissions=True)
		file.reload()
		from frappe.core.doctype.file.file import has_permission as native_file_has_permission

		self.assertFalse(native_file_has_permission(file, "read", self.other.user_id))

	def test_stale_alias_and_mapping_are_rejected_before_apply(self):
		pan_targets = my_details._fields()["pan"]["targets"]
		if len(pan_targets) < 2:
			self.skipTest("This HRMS version has only one PAN storage alias")
		request = self.begin({"pan": "BBBBB1234B"})
		self.add_proof(request, "pan")
		self.submit(request)
		review = self.review(request)
		frappe.db.set_value("Employee", self.employee.name, pan_targets[1], "ALIAS1234A")
		with self.assertRaises(frappe.ValidationError):
			my_details.decide_request(
				request["name"], "Approved", review["review_token"], ["pan"], "Verified"
			)
		self.assertEqual(self.value(self.employee, "pan"), "ABCDE1234F")
		frappe.set_user(self.employee.user_id)
		self.employee.db_set("user_id", self.other.user_id)
		with self.assertRaises(frappe.PermissionError):
			my_details.submit_request(request["name"], consent=True)

	def test_private_proofs_are_per_request_and_raw_mutation_or_deletion_is_blocked(self):
		first = self.begin({"pan": "BBBBB1234B"})
		self.add_proof(first, "pan")
		frappe.set_user(self.other.user_id)
		second = self.begin({"pan": "CCCCC1234C"})
		self.add_proof(second, "pan")
		first_file = frappe.get_doc("File", frappe.get_value(my_details.DOCTYPE, first["name"], "pan_proof"))
		second_file = frappe.get_doc(
			"File", frappe.get_value(my_details.DOCTYPE, second["name"], "pan_proof")
		)
		self.assertTrue(first_file.is_private and second_file.is_private)
		self.assertEqual((first_file.owner, second_file.owner), ("Administrator", "Administrator"))
		self.assertNotEqual(first_file.name, second_file.name)
		self.assertNotEqual(first_file.file_url, second_file.file_url)
		self.assertEqual(first_file.get_content(encodings=[]), second_file.get_content(encodings=[]))
		frappe.set_user("Administrator")
		request_doc = frappe.get_doc(my_details.DOCTYPE, first["name"])
		request_doc.status = "Approved"
		with self.assertRaises(frappe.PermissionError):
			request_doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc(my_details.DOCTYPE, first["name"], ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("File", first_file.name, ignore_permissions=True)

	def test_paired_pan_ifsc_and_available_native_statutory_fields_apply_together(self):
		changes = {"pan": "BBBBB1234B", "ifsc": "HDFC0001234"}
		for key, value in (("uan", "123456789012"), ("esi", "1234567890")):
			if key in my_details._fields():
				changes[key] = value
		request = self.begin(changes)
		self.add_proof(request, "pan")
		self.add_proof(request, "bank")
		if "uan" in changes or "esi" in changes:
			self.add_proof(request, "statutory")
		self.submit(request)
		review = self.review(request)
		approved = my_details.decide_request(
			request["name"], "Approved", review["review_token"], list(changes), "All verified"
		)
		self.assertEqual(approved["status"], "Approved")
		for key, value in changes.items():
			for field in my_details._fields()[key]["targets"]:
				self.assertEqual(frappe.db.get_value("Employee", self.employee.name, field), value)

	def test_stale_employee_review_rejects_without_partial_write(self):
		request = self.begin({"city": "Stale City", "state": "New State"})
		self.submit(request)
		review = self.review(request)
		self.set_value(self.employee, "city", "Externally Changed")
		with self.assertRaises(frappe.ValidationError):
			my_details.decide_request(
				request["name"], "Approved", review["review_token"], ["city", "state"], "Verified"
			)
		self.assertEqual(self.value(self.employee, "city"), "Externally Changed")
		self.assertNotEqual(self.value(self.employee, "state"), "New State")
		self.assertEqual(frappe.get_value(my_details.DOCTYPE, request["name"], "status"), "Pending review")

	def test_stale_request_review_token_rejects_without_writing_employee(self):
		request = self.begin({"city": "Request Stale City"})
		self.submit(request)
		review = self.review(request)
		# Simulate a concurrent, otherwise-valid request update after the reviewer
		# opened it.  Direct DB mutation avoids relying on a forbidden generic save.
		frappe.db.set_value(my_details.DOCTYPE, request["name"], "review_note", "Concurrent update")
		with self.assertRaises(frappe.ValidationError):
			my_details.decide_request(
				request["name"], "Approved", review["review_token"], ["city"], "Verified"
			)
		self.assertEqual(self.value(self.employee, "city"), "Old City")
		self.assertEqual(frappe.get_value(my_details.DOCTYPE, request["name"], "status"), "Pending review")

	def test_decision_replay_requires_exactly_the_same_intent(self):
		clean = self.begin({"city": "Approved City"})
		self.submit(clean)
		review = self.review(clean)
		decision = my_details.decide_request(
			clean["name"], "Approved", review["review_token"], ["city"], "Verified"
		)
		self.assertEqual(
			my_details.decide_request(
				clean["name"], "Approved", review["review_token"], ["city"], "Verified"
			),
			decision,
		)
		with self.assertRaises(frappe.ValidationError):
			my_details.decide_request(
				clean["name"], "Approved", review["review_token"], ["city"], "Different note"
			)

	def test_correction_creates_new_request_without_mutating_the_original(self):
		original = self.begin({"city": "Corrected City"})
		self.submit(original)
		review = self.review(original)
		result = my_details.decide_request(
			original["name"],
			"Needs correction",
			review["review_token"],
			[],
			"Please provide your city in full",
		)
		self.assertEqual(result["status"], "Needs correction")
		before = frappe.get_value(
			my_details.DOCTYPE, original["name"], ["changes_json", "baseline_json"], as_dict=True
		)
		frappe.set_user(self.employee.user_id)
		retry = self.begin({"city": "Corrected City Again"}, retry_of=original["name"])
		self.assertEqual(retry["retry_of"], original["name"])
		self.assertEqual(
			frappe.get_value(
				my_details.DOCTYPE, original["name"], ["changes_json", "baseline_json"], as_dict=True
			),
			before,
		)
		self.assertEqual(json.loads(before.changes_json), {"city": "Corrected City"})

	@skipUnless(
		os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("HRMS_CONCURRENCY_ACCEPTANCE") == "1",
		"Separate CI-only concurrent identity approval acceptance",
	)
	def test_concurrent_duplicate_pan_approval_has_exactly_one_winner(self):
		result = _run_duplicate_pan_concurrency_acceptance(self)
		self.assertEqual(result["result"], "PASS")


def _run_duplicate_pan_concurrency_acceptance(case):
	"""Use disposable CI connections only; committed fixtures make the race physical."""
	from concurrent.futures import ThreadPoolExecutor
	from threading import Barrier

	if frappe.local.site != "test_site" or os.environ.get("GITHUB_ACTIONS") != "true":
		raise RuntimeError("Concurrency fixture is restricted to disposable GitHub CI")
	shared_pan = "QQQQQ1234Q"
	frappe.set_user(case.employee.user_id)
	first = case.begin({"pan": shared_pan}, request_id="race-first-" + case.ident)
	case.add_proof(first, "pan")
	case.submit(first)
	frappe.set_user(case.other.user_id)
	second = case.begin({"pan": shared_pan}, request_id="race-second-" + case.ident)
	case.add_proof(second, "pan")
	case.submit(second)
	frappe.set_user(case.reviewer.user_id)
	first_review = case.review(first)
	second_review = case.review(second)
	frappe.db.commit()  # nosemgrep: required to expose fixtures to CI-only connections

	site = frappe.local.site
	sites_path = frappe.local.sites_path
	barrier = Barrier(2)

	def approve(request, token):
		for attempt in range(4):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.flags.in_test = True
				frappe.conf.enable_employee_my_details = 1
				frappe.set_user(case.reviewer.user_id)
				if attempt == 0:
					barrier.wait(timeout=30)
				result = my_details.decide_request(
					request["name"], "Approved", token, ["pan"], "Concurrent verification"
				)
				frappe.db.commit()  # nosemgrep: separate successful HTTP transaction simulation
				return {"outcome": "approved", "name": result["name"]}
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
				if attempt == 3:
					raise
			except frappe.ValidationError:
				frappe.db.rollback()
				return {"outcome": "blocked", "name": request["name"]}
			finally:
				frappe.destroy()

	with ThreadPoolExecutor(max_workers=2) as pool:
		outcomes = list(
			pool.map(
				lambda args: approve(*args),
				[(first, first_review["review_token"]), (second, second_review["review_token"])],
			)
		)
	# Start a fresh read transaction so MariaDB does not retain the pre-race snapshot.
	frappe.db.rollback()
	frappe.set_user("Administrator")
	try:
		assert [outcome["outcome"] for outcome in outcomes].count("approved") == 1, outcomes
		assert frappe.db.count("Employee", {case.target("pan"): shared_pan, "status": "Active"}) == 1
		return {"approvals": 1, "blocked_duplicates": 1, "result": "PASS"}
	finally:
		frappe.db.rollback()
