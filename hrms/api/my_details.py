"""Session-bound employee profile proposals. Payroll reads Employee until HR approves.

Opt in with enable_employee_my_details. No emails, onboarding tokens, access grants,
accounting documents or schedules are changed. All writes use narrow service APIs;
request and proof guards remain active when the feature is switched off.
"""

import hashlib
import hmac
import io
import json
import re
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, today, validate_email_address

DOCTYPE = "Employee Detail Change Request"
PROOFS = {
	"bank": "bank_proof",
	"pan": "pan_proof",
	"aadhaar": "aadhaar_proof",
	"statutory": "statutory_proof",
}
# Same paired PAN/IFSC and review semantics as solara_master_data_review. Native
# payroll UAN/ESI and emergency fields move with their legacy custom aliases too.
SPECS = [
	("bank_name", "Bank name", "Bank", ("bank_name",), "text", "bank"),
	("bank_holder", "Account holder", "Bank", ("custom_bank_account_holder",), "text", "bank"),
	("bank_account", "Account number", "Bank", ("bank_ac_no",), "bank", "bank"),
	("ifsc", "IFSC", "Bank", ("ifsc_code", "custom_ifsc_code"), "ifsc", "bank"),
	("pan", "PAN", "Identity", ("pan_number", "custom_pan_number"), "pan", "pan"),
	("aadhaar", "Aadhaar", "Identity", ("custom_aadhaar_number",), "aadhaar", "aadhaar"),
	("current_address", "Current address", "Contact", ("current_address",), "textarea", ""),
	("permanent_address", "Permanent address", "Contact", ("permanent_address",), "textarea", ""),
	("city", "City", "Contact", ("custom_city",), "text", ""),
	("state", "State", "Contact", ("custom_state",), "text", ""),
	("pin_code", "PIN code", "Contact", ("custom_pin_code",), "pin", ""),
	("mobile", "Personal mobile", "Contact", ("cell_number",), "mobile", ""),
	("personal_email", "Personal email", "Contact", ("personal_email",), "email", ""),
	(
		"emergency_name",
		"Contact name",
		"Emergency contact",
		("person_to_be_contacted", "custom_emergency_contact_name"),
		"text",
		"",
	),
	(
		"emergency_relation",
		"Relationship",
		"Emergency contact",
		("relation", "custom_emergency_contact_relation"),
		"text",
		"",
	),
	(
		"emergency_phone",
		"Contact phone",
		"Emergency contact",
		("emergency_phone_number", "custom_emergency_contact_phone"),
		"mobile",
		"",
	),
	("uan", "UAN", "PF, ESI & nominee", ("uan_number", "custom_uan"), "uan", "statutory"),
	("esi", "ESI IP number", "PF, ESI & nominee", ("esic_card_no", "custom_esi_no"), "esi", "statutory"),
	("nominee_name", "Nominee name", "PF, ESI & nominee", ("custom_pf_nominee_name",), "text", ""),
	(
		"nominee_relation",
		"Nominee relationship",
		"PF, ESI & nominee",
		("custom_pf_nominee_relation",),
		"relation",
		"",
	),
	("nominee_dob", "Nominee date of birth", "PF, ESI & nominee", ("custom_pf_nominee_dob",), "date", ""),
]
SENSITIVE = {"bank_account", "aadhaar", "pan", "uan", "esi"}
PATTERNS = {
	"bank": r"[0-9]{9,18}",
	"ifsc": r"[A-Z]{4}0[A-Z0-9]{6}",
	"pan": r"[A-Z]{5}[0-9]{4}[A-Z]",
	"aadhaar": r"[2-9][0-9]{11}",
	"uan": r"[0-9]{12}",
	"esi": r"[0-9]{10}",
	"mobile": r"[6-9][0-9]{9}",
	"pin": r"[1-9][0-9]{5}",
}
RELATIONS = ["Spouse", "Father", "Mother", "Son", "Daughter", "Brother", "Sister", "Other"]


def _clean(value):
	return "" if value is None else str(value).strip()


def _json(value):
	return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _token(value):
	return hmac.new(
		frappe.local.conf.encryption_key.encode(), _json(value).encode(), hashlib.sha256
	).hexdigest()


def _signin():
	if frappe.session.user == "Guest" or not frappe.db.get_value("User", frappe.session.user, "enabled"):
		frappe.throw(_("Please sign in with your employee account."), frappe.PermissionError)


def _enabled():
	_signin()
	if not cint(frappe.conf.get("enable_employee_my_details")):
		frappe.throw(_("My Details is not enabled. Please contact HR."), frappe.PermissionError)


def _employee(lock=False):
	rows = frappe.get_all(
		"Employee", filters={"user_id": frappe.session.user, "status": "Active"}, pluck="name", limit=2
	)
	if len(rows) != 1:
		frappe.throw(
			_("Your login must be linked to exactly one active employee. Please contact HR."),
			frappe.PermissionError,
		)
	emp = _load_employee(rows[0], lock)
	if emp.user_id != frappe.session.user:
		frappe.throw(_("Your employee link changed. Sign in again."), frappe.PermissionError)
	return emp


def _load_employee(name, lock=False):
	if lock:
		frappe.db.sql("select name from `tabEmployee` where name=%s for update", name)
	emp = frappe.get_doc("Employee", name, for_update=lock)
	if emp.status != "Active":
		frappe.throw(_("This employee is no longer active."), frappe.PermissionError)
	return emp


def _fields():
	meta = frappe.get_meta("Employee")
	return {
		key: {
			"key": key,
			"label": label,
			"group": group,
			"targets": [f for f in targets if meta.has_field(f)],
			"type": kind,
			"proof": proof,
		}
		for key, label, group, targets, kind, proof in SPECS
		if any(meta.has_field(f) for f in targets)
	}


def _snapshot(emp):
	return {f: _clean(emp.get(f)) for spec in _fields().values() for f in spec["targets"]}


def _version(emp):
	return _token([emp.name, emp.user_id, emp.status, emp.company, _snapshot(emp)])


def _mask(key, value):
	return "•••• " + value[-4:] if key in SENSITIVE and value else value


def _can_review(emp, user=None):
	user = user or frappe.session.user
	return bool(
		user != "Guest"
		and frappe.db.get_value("User", user, "enabled")
		and (
			user == "Administrator"
			or frappe.db.exists(
				"Has Role",
				{"parent": user, "parenttype": "User", "role": ["in", ["HR Manager", "System Manager"]]},
			)
		)
		and frappe.has_permission("Employee", "write", doc=emp, user=user)
	)


def _require_review(emp):
	if not _can_review(emp) or emp.user_id == frappe.session.user:
		frappe.throw(
			_("An authorised HR reviewer other than the employee must review this request."),
			frappe.PermissionError,
		)


@contextmanager
def _operation(doc):
	previous = getattr(frappe.local, "my_details_operation", None)
	frappe.local.my_details_operation = doc
	try:
		yield
	finally:
		frappe.local.my_details_operation = previous


def guard_write(doc, method=None):
	if getattr(frappe.local, "my_details_operation", None) is not doc:
		frappe.throw(
			_("Use My Details to submit or review a change request. History cannot be edited or deleted."),
			frappe.PermissionError,
		)


def _save(doc, new=False):
	with _operation(doc):
		return doc.insert(ignore_permissions=True) if new else doc.save(ignore_permissions=True)


def has_permission(doc, ptype=None, user=None, debug=False):
	# Employees receive only masked, allowlisted API responses, never raw snapshots.
	if ptype not in ("read", "select") or not doc.get("employee"):
		return False
	return _can_review(frappe.get_doc("Employee", doc.employee), user)


def permission_query(user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	if not frappe.db.exists(
		"Has Role", {"parent": user, "parenttype": "User", "role": ["in", ["HR Manager", "System Manager"]]}
	):
		return "1=0"
	return ""  # Native Employee/Company User Permissions further constrain this list.


def guard_file(doc, method=None):
	previous = frappe.db.get_value("File", doc.name, "attached_to_doctype") if not doc.is_new() else None
	if DOCTYPE in (doc.attached_to_doctype, previous):
		guard_write(doc)
		if not doc.is_private or doc.owner != "Administrator":
			frappe.throw(_("Profile proof must remain private."), frappe.PermissionError)


def _request(name, emp=None, lock=False):
	# Identity check happens before locks/reads that return any request contents.
	linked = frappe.db.get_value(DOCTYPE, name, "employee")
	if not linked or (emp and linked != emp.name):
		frappe.throw(_("Request unavailable."), frappe.PermissionError)
	if lock:
		frappe.db.sql(f"select name from `tab{DOCTYPE}` where name=%s for update", name)
	return frappe.get_doc(DOCTYPE, name, for_update=lock)


def _result(doc, reveal=False):
	changes = json.loads(doc.changes_json)
	fields = _fields()
	return {
		"name": doc.name,
		"status": doc.status,
		"created": str(doc.creation),
		"reviewed_on": str(doc.reviewed_on or ""),
		"review_note": doc.review_note or "",
		"applied_fields": json.loads(doc.applied_fields_json or "[]"),
		"changes": [
			{"key": k, "label": fields[k]["label"], "value": v if reveal else _mask(k, v)}
			for k, v in changes.items()
		],
		"proofs": [kind for kind, field in PROOFS.items() if doc.get(field)],
		"required_proofs": sorted({fields[k]["proof"] for k in changes if fields[k]["proof"]}),
		"retry_of": doc.retry_of,
	}


@frappe.whitelist()
def get_context() -> dict:
	_signin()
	if not cint(frappe.conf.get("enable_employee_my_details")):
		return {"enabled": False}
	emp = _employee()
	fields = []
	for key, spec in _fields().items():
		values = [_clean(emp.get(f)) for f in spec["targets"]]
		value = next((v for v in values if v), "")
		fields.append(
			{k: v for k, v in spec.items() if k != "targets"}
			| {
				"value": _mask(key, value),
				"sensitive": key in SENSITIVE,
				"aliases_differ": len(set(v for v in values if v)) > 1,
				"options": RELATIONS if spec["type"] == "relation" else [],
			}
		)
	names = frappe.get_all(
		DOCTYPE, filters={"employee": emp.name}, pluck="name", order_by="creation desc", limit_page_length=100
	)
	return {
		"enabled": True,
		"employee_name": emp.employee_name,
		"version": _version(emp),
		"fields": fields,
		"requests": [_result(frappe.get_doc(DOCTYPE, n)) for n in names],
		"employment": {
			k: emp.get(k)
			for k in ["employee_number", "company", "department", "designation", "date_of_joining"]
		},
	}


@frappe.whitelist()
def reveal_field(field: str) -> dict:
	_enabled()
	emp = _employee()
	if field not in SENSITIVE or field not in _fields():
		frappe.throw(_("Field unavailable."), frappe.PermissionError)
	return {"value": next((_clean(emp.get(f)) for f in _fields()[field]["targets"] if emp.get(f)), "")}


def _normalize(changes):
	fields = _fields()
	if (
		not isinstance(changes, dict)
		or not changes
		or len(changes) > len(fields)
		or set(changes) - fields.keys()
	):
		frappe.throw(_("Choose only supported personal details to update."))
	result = {}
	for key, value in changes.items():
		spec = fields[key]
		if not isinstance(value, str):
			frappe.throw(_("Enter text for {0}.").format(spec["label"]))
		value = value.strip()
		if spec["type"] in ("pan", "ifsc"):
			value = value.upper()
		if (
			not value
			or len(value) > (2000 if spec["type"] == "textarea" else 140)
			or any(ord(c) < 32 and c not in "\n\t" for c in value)
		):
			frappe.throw(
				_("Enter a valid {0}. To remove a recorded value, contact HR.").format(spec["label"])
			)
		pattern = PATTERNS.get(spec["type"])
		if pattern and not re.fullmatch(pattern, value, flags=re.ASCII):
			frappe.throw(_("Check the format of {0}.").format(spec["label"]))
		if spec["type"] == "email":
			validate_email_address(value, throw=True)
		if spec["type"] == "date":
			if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) or getdate(value) > getdate(today()):
				frappe.throw(_("Enter a valid date of birth in the past."))
		if spec["type"] == "relation" and value not in RELATIONS:
			frappe.throw(_("Choose a listed nominee relationship."))
		result[key] = value
	return result


@frappe.whitelist(methods=["POST"])
def begin_request(changes: dict | str, expected_version: str, request_id: str, retry_of: str = "") -> dict:
	_enabled()
	changes = _normalize(frappe.parse_json(changes))
	if not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", request_id):
		frappe.throw(_("Invalid request ID. Refresh and try again."))
	emp = _employee(lock=True)
	name = "EDC-" + hashlib.sha256((emp.name + ":" + request_id).encode()).hexdigest()[:32]
	if frappe.db.sql(f"select name from `tab{DOCTYPE}` where name=%s for update", name):
		old = _request(name, emp)
		if json.loads(old.changes_json) != changes or (old.retry_of or "") != retry_of:
			frappe.throw(_("This retry contains different details. Resume the saved request or start again."))
		return _result(old)
	if not hmac.compare_digest(_version(emp), expected_version):
		frappe.throw(_("Your approved details changed. Refresh and review them before submitting."))
	if frappe.db.sql(
		f"select name from `tab{DOCTYPE}` where employee=%s and status in ('Draft','Pending review') for update",
		emp.name,
	):
		frappe.throw(_("You already have an unfinished request. Resume it or wait for HR review."))
	if retry_of and _request(retry_of, emp).status != "Needs correction":
		frappe.throw(_("Only a request needing correction can be resubmitted."))
	baseline = {f: _clean(emp.get(f)) for k in changes for f in _fields()[k]["targets"]}
	if any(all(_clean(emp.get(f)) == v for f in _fields()[k]["targets"]) for k, v in changes.items()):
		frappe.throw(_("Remove unchanged details before submitting."))
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"name": name,
			"employee": emp.name,
			"company": emp.company,
			"requested_by": frappe.session.user,
			"status": "Draft",
			"changes_json": _json(changes),
			"baseline_json": _json(baseline),
			"retry_of": retry_of,
		}
	)
	_save(doc, new=True)
	return _result(doc)


def _valid_content(content, filename):
	if not content or len(content) > 5 * 1024 * 1024:
		frappe.throw(_("Choose a PDF, JPG or PNG file up to 5 MB."))
	ext = Path(filename).suffix.lower()
	if ext == ".pdf" and content.startswith(b"%PDF-"):
		from frappe.utils.pdf import pdf_contains_js

		if pdf_contains_js(content):
			frappe.throw(_("This PDF contains unsafe content. Upload a plain document."))
	elif ext in (".jpg", ".jpeg", ".png"):
		try:
			with Image.open(io.BytesIO(content)) as image:
				if image.format not in ("JPEG", "PNG"):
					raise ValueError
				image.verify()
		except Exception:
			frappe.throw(_("The image could not be read. Upload a JPG or PNG."))
	else:
		frappe.throw(_("Choose a PDF, JPG or PNG file up to 5 MB."))
	return ext


@frappe.whitelist(methods=["POST"])
def upload_proof(request: str, kind: str) -> dict:
	_enabled()
	emp = _employee(lock=True)
	doc = _request(request, emp, lock=True)
	if doc.status != "Draft" or kind not in _result(doc)["required_proofs"]:
		frappe.throw(_("This request does not accept that proof."), frappe.PermissionError)
	upload = frappe.request.files.get("file")
	if not upload:
		frappe.throw(_("Choose a file to upload."))
	return _store_proof(doc, kind, upload.read(5 * 1024 * 1024 + 1), upload.filename)


def _store_proof(doc, kind, content, filename):
	ext = _valid_content(content, filename)
	field = PROOFS[kind]
	if doc.get(field):
		existing = frappe.get_doc("File", doc.get(field))
		if hashlib.sha256(existing.get_content(encodings=[])).digest() != hashlib.sha256(content).digest():
			frappe.throw(_("A different proof is already saved. Discard this draft to start a new request."))
		return {"kind": kind, "saved": True}
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"profile-{frappe.generate_hash(length=24)}{ext}",
			"content": content,
			"is_private": 1,
			"owner": "Administrator",
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": doc.name,
		}
	)
	# Never share a deduplicated blob with another employee's attachment. Prewrite a
	# unique private blob, then use the pinned framework's copy lifecycle to preserve it.
	file.flags.new_file = True
	file.save_file(content=content, ignore_existing_file_check=True)
	file.flags.copy_from_existing_file = True
	with _operation(file):
		file.insert(ignore_permissions=True)
	doc.set(field, file.name)
	_save(doc)
	return {"kind": kind, "saved": True}


def _proofs(doc):
	for kind in _result(doc)["required_proofs"]:
		name = doc.get(PROOFS[kind])
		if not name:
			frappe.throw(_("Upload the {0} proof before submitting.").format(kind))
		file = frappe.get_doc("File", name)
		if (
			not file.is_private
			or file.owner != "Administrator"
			or file.attached_to_doctype != DOCTYPE
			or file.attached_to_name != doc.name
			or not file.file_url.startswith("/private/files/")
		):
			frappe.throw(_("Proof ownership could not be verified."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def submit_request(request: str, consent: bool = False) -> dict:
	_enabled()
	emp = _employee(lock=True)
	doc = _request(request, emp, lock=True)
	if doc.status == "Withdrawn":
		frappe.throw(_("This draft was discarded. Start a new request."))
	if doc.status != "Draft":
		return _result(doc)
	if not cint(consent):
		frappe.throw(
			_("Confirm that these details and documents are accurate and may be stored for HR review.")
		)
	_assert_baseline(doc, emp)
	_proofs(doc)
	doc.status = "Pending review"
	doc.consented_on = now_datetime()
	_save(doc)
	doc.add_comment(
		"Info", "Employee submitted personal-detail changes for HR review. Approved master values unchanged."
	)
	return _result(doc)


@frappe.whitelist(methods=["POST"])
def discard_draft(request: str) -> dict:
	_enabled()
	doc = _request(request, _employee(lock=True), lock=True)
	if doc.status not in ("Draft", "Withdrawn"):
		frappe.throw(_("Only an unsubmitted draft can be discarded."))
	doc.status = "Withdrawn"
	_save(doc)
	return _result(doc)


def _assert_baseline(doc, emp):
	expected_targets = {f for k in json.loads(doc.changes_json) for f in _fields()[k]["targets"]}
	baseline = json.loads(doc.baseline_json)
	if set(baseline) != expected_targets:
		frappe.throw(_("The Employee field mapping changed. Ask for a fresh request."))
	for field, old in baseline.items():
		if _clean(emp.get(field)) != old:
			frappe.throw(
				_("Approved details changed after this request was prepared. Ask for a corrected request.")
			)


def _duplicates(changes, emp, lock=False):
	blockers = []
	# Lock all active employee rows in name order before approving, serialising
	# approvals across employees too (different employees can propose one ID).
	fields = _fields()
	for key in {"pan", "aadhaar", "bank_account", "uan", "esi"} & changes.keys():
		for target in fields[key]["targets"]:
			rows = frappe.db.sql(
				f"select `{target}` from `tabEmployee` where status='Active' and name!=%s"
				+ (" for update" if lock else ""),
				emp.name,
			)
			if any(re.sub(r"\s+", "", _clean(row[0])).upper() == changes[key] for row in rows):
				blockers.append(fields[key]["label"] + " is already recorded for another active employee.")
				break
	return blockers


@frappe.whitelist()
def review_request(request: str) -> dict:
	_enabled()
	doc = _request(request)
	emp = _load_employee(doc.employee)
	_require_review(emp)
	return _review(doc, emp)


def _review(doc, emp):
	changes = json.loads(doc.changes_json)
	baseline = json.loads(doc.baseline_json)
	fields = _fields()
	return _result(doc, reveal=True) | {
		"employee_name": emp.employee_name,
		"review_token": _token([doc.name, str(doc.modified), str(emp.modified), _snapshot(emp)]),
		"rows": [
			{
				"key": k,
				"label": fields[k]["label"],
				"proposed": v,
				"current": [{"field": f, "value": _clean(emp.get(f))} for f in fields[k]["targets"]],
			}
			for k, v in changes.items()
		],
		"blockers": _duplicates(changes, emp),
		"stale": any(_clean(emp.get(f)) != v for f, v in baseline.items()),
	}


@frappe.whitelist(methods=["POST"])
def decide_request(
	request: str, decision: str, review_token: str, selected: list | str, note: str = ""
) -> dict:
	_enabled()
	initial = _request(request)
	emp = _load_employee(initial.employee)
	_require_review(emp)
	if decision not in ("Approved", "Needs correction"):
		frappe.throw(_("Choose Approve or Needs correction."))
	selected = frappe.parse_json(selected)
	if (
		not isinstance(selected, list)
		or any(not isinstance(k, str) for k in selected)
		or len(set(selected)) != len(selected)
	):
		frappe.throw(_("Choose the fields to approve."))
	note = _clean(note)
	if len(note) > 1000 or (decision == "Needs correction" and len(note) < 5):
		frappe.throw(_("Explain what needs correcting (5–1000 characters)."))
	# One consistent order avoids opposite-employee approval deadlocks. Locking
	# reads see committed state even after a previous read in MariaDB RR isolation.
	frappe.db.sql("select name from `tabEmployee` where status='Active' order by name for update")
	emp = _load_employee(initial.employee, lock=True)
	_require_review(emp)
	doc = _request(request, lock=True)
	fingerprint = _token([decision, sorted(selected), note, frappe.session.user, review_token])
	if doc.status != "Pending review":
		if doc.decision_fingerprint == fingerprint:
			return _result(doc)
		frappe.throw(_("This request has already been reviewed. Refresh to see the decision."))
	current = _review(doc, emp)
	if not hmac.compare_digest(current["review_token"], review_token):
		frappe.throw(_("The request or Employee changed after you opened the review. Review again."))
	changes = json.loads(doc.changes_json)
	if set(selected) - changes.keys():
		frappe.throw(_("Choose only submitted fields."))
	if decision == "Approved":
		if not selected:
			frappe.throw(_("Select at least one field to approve."))
		if len(selected) != len(changes) and len(note) < 5:
			frappe.throw(_("Explain why the remaining fields are being kept unchanged."))
		_assert_baseline(doc, emp)
		_proofs(doc)
		approved = _normalize({k: changes[k] for k in selected})
		blockers = _duplicates(approved, emp, lock=True)
		if blockers:
			frappe.throw(" ".join(blockers))
		for key, value in approved.items():
			for field in _fields()[key]["targets"]:
				emp.set(field, value)
		emp.save(ignore_permissions=True)
		emp.add_comment(
			"Info",
			f"Personal details updated after HR review of {doc.name}. Fields: "
			+ ", ".join(_fields()[k]["label"] for k in selected),
		)
	elif selected:
		frappe.throw(_("Do not select fields when requesting a correction."))
	doc.status = decision
	doc.review_note = note
	doc.reviewed_by = frappe.session.user
	doc.reviewed_on = now_datetime()
	doc.applied_fields_json = _json(selected)
	doc.decision_fingerprint = fingerprint
	_save(doc)
	doc.add_comment(
		"Info",
		f"{decision} by {frappe.session.user}. Approved fields: "
		+ ", ".join(_fields()[k]["label"] for k in selected),
	)
	return _result(doc)


@frappe.whitelist()
def download_proof(request: str, kind: str) -> None:
	_enabled()
	doc = _request(request)
	emp = _load_employee(doc.employee)
	if not _can_review(emp):
		own = _employee()
		if own.name != doc.employee:
			frappe.throw(_("Proof unavailable."), frappe.PermissionError)
	if kind not in PROOFS or not doc.get(PROOFS[kind]):
		frappe.throw(_("Proof unavailable."), frappe.PermissionError)
	_proofs(doc)
	file = frappe.get_doc("File", doc.get(PROOFS[kind]))
	frappe.local.response.filename = kind + Path(file.file_name).suffix
	frappe.local.response.filecontent = file.get_content(encodings=[])
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "attachment"


@frappe.whitelist()
def get_profile() -> dict:
	"""Narrow replacement for the old Profile page's fields='*' Employee fetch."""
	_signin()
	emp = _employee()
	keys = [
		"employee_name",
		"employee_number",
		"gender",
		"date_of_birth",
		"date_of_joining",
		"blood_group",
		"company",
		"department",
		"designation",
		"branch",
		"grade",
		"reports_to",
		"employment_type",
		"cell_number",
		"personal_email",
		"company_email",
		"prefered_contact_email",
		"ctc",
		"salary_currency",
		"payroll_cost_center",
		"salary_mode",
	]
	return {
		"values": {key: emp.get(key) for key in keys},
		"fields": [
			{"fieldname": f.fieldname, "label": f.label, "fieldtype": f.fieldtype}
			for f in frappe.get_meta("Employee").fields
			if f.fieldname in keys
		],
		"my_details_enabled": bool(cint(frappe.conf.get("enable_employee_my_details"))),
	}
