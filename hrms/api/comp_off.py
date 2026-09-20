"""Opt-in employee comp-off credit requests; manager approval uses the native ledger.

Enable with enable_comp_off_self_service after migration and verified TEST evidence.
The API never accepts an employee, approver, leave type, credit amount or status from
an employee. Employee REST/Desk mutations are blocked while enabled, and portal
records stay protected when the site flag is switched off. No email is sent.
"""

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, now_datetime, today

from hrms.api.comp_off_recovery import reverse_unused_portal_credit
from hrms.hr.utils import get_holiday_dates_for_employee, get_leave_period

DOCTYPE = "Compensatory Leave Request"
LEAVE_TYPE = "Compensatory Off"
FIELDS = [
	"name",
	"employee",
	"employee_name",
	"work_from_date",
	"work_end_date",
	"half_day",
	"reason",
	"portal_status",
	"creation",
	"decision_by",
	"decision_on",
	"decision_reason",
	"leave_allocation",
	"docstatus",
	"portal_request",
]


def enabled():
	return bool(cint(frappe.conf.get("enable_comp_off_self_service")))


def _require_enabled():
	if not enabled():
		frappe.throw(_("Comp-off credit requests are not enabled. Please contact HR."))
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in."), frappe.PermissionError)


def _employee(user=None):
	rows = frappe.get_all(
		"Employee",
		filters={"user_id": user or frappe.session.user, "status": "Active"},
		fields=["name", "employee_name", "user_id", "reports_to", "company", "date_of_joining"],
		limit=2,
	)
	if len(rows) != 1:
		frappe.throw(_("Your login must be linked to exactly one active employee. Please contact HR."))
	return rows[0]


def _manager(employee):
	if not employee.reports_to or employee.reports_to == employee.name:
		return None
	manager = frappe.db.get_value(
		"Employee",
		{"name": employee.reports_to, "status": "Active"},
		["name", "employee_name", "user_id", "company"],
		as_dict=True,
	)
	if (
		not manager
		or not manager.user_id
		or manager.user_id == employee.user_id
		or manager.company != employee.company
		or not frappe.db.get_value("User", manager.user_id, "enabled")
	):
		return None
	return manager


def _can_approve(employee):
	manager = _manager(employee)
	return bool(
		manager and manager.user_id == frappe.session.user and employee.user_id != frappe.session.user
	)


def _employee_by_name(name):
	employee = frappe.db.get_value(
		"Employee",
		{"name": name, "status": "Active"},
		["name", "employee_name", "user_id", "reports_to", "company", "date_of_joining"],
		as_dict=True,
	)
	if not employee:
		frappe.throw(_("The employee is no longer active. Please contact HR."))
	return employee


def _lock_employee(employee):
	# All credit requests for an employee share this lock, including first allocation creation.
	frappe.db.sql("select name from `tabEmployee` where name=%s for update", employee)


@contextmanager
def _operation(doc, action):
	previous = getattr(frappe.local, "comp_off_operation", None)
	frappe.local.comp_off_operation = (doc, action)
	try:
		yield
	finally:
		frappe.local.comp_off_operation = previous


def _native_hr_user(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(
		frappe.db.get_value("User", user, "enabled")
		and set(frappe.get_roles(user)) & {"HR Manager", "HR User", "System Manager"}
	)


def guard_write(doc):
	stored = None
	if not doc.is_new():
		stored = frappe.db.get_value(DOCTYPE, doc.name, "portal_request")
	if not (doc.get("portal_request") or stored) and (not enabled() or _native_hr_user()):
		return
	operation = getattr(frappe.local, "comp_off_operation", None)
	if (
		not operation
		or operation[0] is not doc
		or operation[1] not in ("create", "approve", "reject", "recover")
	):
		frappe.throw(
			_("Use the employee portal to request or review comp-off credit."), frappe.PermissionError
		)


def validate_portal_request(doc):
	if doc.portal_status == "Rejected":
		return
	if doc.work_from_date != doc.work_end_date or getdate(doc.work_from_date) > getdate(today()):
		frappe.throw(_("Choose one completed work date for each request."))
	attendance = frappe.get_all(
		"Attendance",
		filters={"employee": doc.employee, "attendance_date": doc.work_from_date, "docstatus": 1},
		fields=["status"],
	)
	if len(attendance) != 1 or attendance[0].status not in ("Present", "Work From Home", "Half Day"):
		frappe.throw(_("HR must verify one submitted attendance record for this work date."))
	if cint(doc.half_day) != int(attendance[0].status == "Half Day"):
		frappe.throw(
			_(
				"Attendance changed after this request. Reject it so the employee can request the correct credit."
			)
		)
	if doc.leave_type != LEAVE_TYPE or not frappe.db.get_value("Leave Type", LEAVE_TYPE, "is_compensatory"):
		frappe.throw(_("HR must configure the Compensatory Off leave type before you can request credit."))
	if not get_leave_period(
		add_days(doc.work_end_date, 1),
		add_days(doc.work_end_date, 1),
		frappe.db.get_value("Employee", doc.employee, "company"),
	):
		frappe.throw(_("HR must set up an active leave period for this work date."))
	if frappe.db.sql(
		"""select name from `tabCompensatory Leave Request`
		where employee=%s and name!=%s and docstatus<2
		and coalesce(portal_status, '')!='Rejected'
		and work_from_date<=%s and work_end_date>=%s limit 1 for update""",
		(doc.employee, doc.name or "", doc.work_end_date, doc.work_from_date),
	):
		frappe.throw(_("A comp-off credit request already exists for this work date."))


def _result(doc):
	result = {key: doc.get(key) for key in FIELDS}
	result["status"] = result.pop("portal_status") or ("Approved" if doc.docstatus == 1 else "Pending")
	if doc.docstatus == 2:
		result["status"] = "Cancelled"
	result["can_approve"] = bool(
		doc.docstatus == 0 and result["status"] == "Pending" and _can_approve(_employee_by_name(doc.employee))
	)
	return result


@frappe.whitelist()
def get_context() -> dict:
	if not enabled():
		return {"enabled": False}
	_require_enabled()
	employee = _employee()
	manager = _manager(employee)
	attendance = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee.name,
			"docstatus": 1,
			"status": ["in", ["Present", "Work From Home", "Half Day"]],
			"attendance_date": ["<=", today()],
		},
		fields=["attendance_date", "status"],
		order_by="attendance_date desc",
		limit_page_length=0,
	)
	eligible = []
	if attendance:
		holidays = {
			getdate(d)
			for d in get_holiday_dates_for_employee(
				employee.name, attendance[-1].attendance_date, attendance[0].attendance_date
			)
		}
		requests = frappe.get_all(
			DOCTYPE,
			filters={"employee": employee.name, "docstatus": ["<", 2]},
			fields=["work_from_date", "work_end_date", "portal_status"],
		)
		for row in attendance:
			date = getdate(row.attendance_date)
			if sum(getdate(other.attendance_date) == date for other in attendance) != 1:
				continue
			if date in holidays and not any(
				r.portal_status != "Rejected"
				and getdate(r.work_from_date) <= date <= getdate(r.work_end_date)
				for r in requests
			):
				eligible.append({"date": str(date), "half_day": row.status == "Half Day"})
	return {
		"enabled": True,
		"employee": {"name": employee.name, "employee_name": employee.employee_name},
		"manager": {"user_id": manager.user_id, "employee_name": manager.employee_name} if manager else None,
		"is_manager": bool(frappe.db.exists("Employee", {"reports_to": employee.name, "status": "Active"})),
		"leave_type": LEAVE_TYPE,
		"eligible_dates": eligible,
	}


@frappe.whitelist()
def get_requests(team: int = 0) -> list[dict]:
	_require_enabled()
	employee = _employee()
	if cint(team):
		employees = frappe.get_all(
			"Employee",
			filters={
				"reports_to": employee.name,
				"status": "Active",
				"company": employee.company,
				"name": ["!=", employee.name],
			},
			pluck="name",
		)
	else:
		employees = [employee.name]
	if not employees:
		return []
	rows = frappe.get_all(
		DOCTYPE,
		filters={"employee": ["in", employees], "portal_request": 1, "docstatus": ["<", 2]},
		fields=FIELDS,
		order_by="creation desc",
		limit_page_length=0,
	)
	return [_result(row) for row in rows]


@frappe.whitelist(methods=["POST"])
def create_request(work_date: str, reason: str, half_day: int = 0) -> dict:
	_require_enabled()
	employee = _employee()
	_lock_employee(employee.name)
	# Read current manager after acquiring the serialization lock.
	employee = _employee_by_name(employee.name)
	if not _manager(employee):
		frappe.throw(_("Your reporting manager needs an active Atlas login. Please contact HR."))
	if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 1000:
		frappe.throw(_("Describe the work completed in 1 to 1,000 characters."))
	if str(half_day) not in ("0", "1", "False", "True"):
		frappe.throw(_("Choose a full day or half day."))
	date = getdate(work_date)
	if not work_date or date > getdate(today()) or date < getdate(employee.date_of_joining):
		frappe.throw(_("Choose a completed work date on or after your joining date."))
	attendance = frappe.get_all(
		"Attendance",
		filters={"employee": employee.name, "attendance_date": date, "docstatus": 1},
		fields=["status"],
	)
	if len(attendance) != 1 or attendance[0].status not in ("Present", "Work From Home", "Half Day"):
		frappe.throw(_("HR must verify one submitted attendance record for this work date."))
	verified_half_day = int(attendance[0].status == "Half Day")
	if cint(half_day) != verified_half_day:
		frappe.throw(_("Your attendance changed. Refresh the page before requesting credit."))
	half_day = verified_half_day
	existing = frappe.db.sql(
		"""select name, work_from_date, work_end_date, half_day, reason, portal_request
		from `tabCompensatory Leave Request` where employee=%s and docstatus<2
		and coalesce(portal_status, '')!='Rejected' and work_from_date<=%s and work_end_date>=%s
		for update""",
		(employee.name, date, date),
		as_dict=True,
	)
	if existing:
		row = existing[0]
		if (
			row.portal_request
			and getdate(row.work_from_date) == date == getdate(row.work_end_date)
			and cint(row.half_day) == half_day
			and row.reason == reason.strip()
		):
			return _result(frappe.get_doc(DOCTYPE, row.name))
		frappe.throw(_("A comp-off credit request already exists for this work date."))
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"employee": employee.name,
			"leave_type": LEAVE_TYPE,
			"work_from_date": date,
			"work_end_date": date,
			"half_day": half_day,
			"half_day_date": date if half_day else None,
			"reason": reason.strip(),
			"portal_request": 1,
			"portal_status": "Pending",
		}
	)
	with _operation(doc, "create"):
		doc.insert(ignore_permissions=True)
	return _result(doc)


@frappe.whitelist(methods=["POST"])
def decide_request(name: str, decision: str, reason: str = "") -> dict:
	_require_enabled()
	if decision not in ("Approved", "Rejected"):
		frappe.throw(_("Choose Approve or Reject."))
	if not isinstance(reason, str) or len(reason.strip()) > 1000:
		frappe.throw(_("Keep your note within 1,000 characters."))
	if decision == "Rejected" and not reason.strip():
		frappe.throw(_("Give the employee a reason for rejecting this request."))
	employee_name = frappe.db.get_value(DOCTYPE, name, "employee")
	if not employee_name or not _can_approve(_employee_by_name(employee_name)):
		frappe.throw(
			_("Only this employee's current reporting manager can review the request."),
			frappe.PermissionError,
		)
	_lock_employee(employee_name)
	frappe.db.sql("select name from `tabCompensatory Leave Request` where name=%s for update", name)
	doc = frappe.get_doc(DOCTYPE, name)
	if not doc.portal_request or not _can_approve(_employee_by_name(doc.employee)):
		frappe.throw(_("You cannot review this request."), frappe.PermissionError)
	if doc.portal_status == decision and (
		(decision == "Approved" and doc.docstatus == 1) or (decision == "Rejected" and doc.docstatus == 0)
	):
		return _result(doc)
	if doc.portal_status != "Pending" or doc.docstatus != 0:
		frappe.throw(_("This request has already been reviewed. Refresh the page."))
	doc.portal_status = decision
	doc.decision_by = frappe.session.user
	doc.decision_on = now_datetime()
	doc.decision_reason = reason.strip()
	doc.flags.ignore_permissions = True
	with _operation(doc, "approve" if decision == "Approved" else "reject"):
		if decision == "Approved":
			_extend_allocation_for_earlier_credit(doc)
			doc.submit()
		else:
			doc.save()
	return _result(doc)


def _extend_allocation_for_earlier_credit(doc):
	"""Keep ledger effective dates intact when holidays are approved out of order.

	Only allocation coverage is extended. Existing dated ledger entries are not
	rewritten; native on_submit adds exactly the new credit at worked-date + 1.
	The caller holds the employee lock and any failure rolls back this change.
	"""
	date = getdate(add_days(doc.work_end_date, 1))
	company = frappe.db.get_value("Employee", doc.employee, "company")
	periods = get_leave_period(date, date, company)
	if len(periods or []) != 1:
		frappe.throw(_("HR must configure exactly one active leave period for this date."))
	period = periods[0]
	rows = frappe.db.sql(
		"""select name, from_date, to_date from `tabLeave Allocation`
		where employee=%s and leave_type=%s and docstatus=1 and to_date>=%s
		and from_date<=%s order by from_date for update""",
		(doc.employee, doc.leave_type, date, period.to_date),
		as_dict=True,
	)
	if any(getdate(row.from_date) <= date <= getdate(row.to_date) for row in rows):
		return
	if rows:
		allocation = frappe.get_doc("Leave Allocation", rows[0].name)
		allocation.from_date = date
		allocation.validate_allocation_overlap()
		allocation.db_set("from_date", date, update_modified=True)


def _read_condition(user):
	user = frappe.db.escape(user)
	return f"""(`tabCompensatory Leave Request`.employee in (
		select employee.name from `tabEmployee` employee
		left join `tabEmployee` manager on manager.name=employee.reports_to and manager.status='Active'
		where employee.user_id={user} or (manager.user_id={user} and employee.status='Active'
		and employee.company=manager.company and coalesce(employee.user_id, '')!={user})))"""


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if user == "Administrator" or set(frappe.get_roles(user)) & {"HR Manager", "HR User", "System Manager"}:
		return ""
	condition = _read_condition(user)
	if not enabled():
		condition = f"(coalesce(`tabCompensatory Leave Request`.portal_request, 0)=0 or {condition})"
	return condition


def has_permission(doc, ptype=None, user=None, debug=False):
	stored = frappe.db.get_value(DOCTYPE, doc.name, "portal_request") if not doc.is_new() else None
	if not (doc.get("portal_request") or stored) and (not enabled() or _native_hr_user(user)):
		return True
	user = user or frappe.session.user
	if ptype not in ("read", "select", "print", "email"):
		return False
	if user == "Administrator" or set(frappe.get_roles(user)) & {"HR Manager", "HR User", "System Manager"}:
		return True
	if not doc.employee:
		return False
	employee = frappe.db.get_value(
		"Employee",
		{"name": doc.employee},
		["name", "employee_name", "user_id", "reports_to", "company"],
		as_dict=True,
	)
	if not employee:
		return False
	manager = _manager(employee)
	if employee.user_id == user or (manager and manager.user_id == user):
		return True
	return False
