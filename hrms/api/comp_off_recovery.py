"""Console-only recovery of unused portal credit during a drained maintenance window.

This is deliberately not whitelisted. LIVE recovery needs separate approval and
the operational write pause documented in docs/comp-off-recovery.md. The caller
owns the transaction; this function never commits.
"""

import html
import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

MARKER = "comp_off_recovery_v1"
LEDGER_FIELDS = (
	"name, employee, leave_type, transaction_type, transaction_name, leaves, "
	"from_date, to_date, is_carry_forward, is_expired, docstatus"
)


def _require(condition, message):
	if not condition:
		frappe.throw(_(message))


def _snapshot(allocation):
	allocation.reload()
	rows = frappe.db.sql(
		f"select {LEDGER_FIELDS} from `tabLeave Ledger Entry` "
		"where transaction_type='Leave Allocation' and transaction_name=%s order by name for update",
		allocation.name,
		as_dict=True,
	)
	return json.loads(
		json.dumps(
			{
				"new": flt(allocation.new_leaves_allocated),
				"total": flt(allocation.total_leaves_allocated),
				"ledger_total": sum(flt(row.leaves) for row in rows if row.docstatus == 1),
				"rows": rows,
			},
			default=str,
		)
	)


def reverse_unused_portal_credit(name, reason):
	"""Reverse a clean, unused credit atomically; return a verified retry unchanged."""
	actor = frappe.session.user
	if actor != "Administrator" and not (
		frappe.db.get_value("User", actor, "enabled")
		and set(frappe.get_roles(actor)) & {"HR Manager", "System Manager"}
	):
		frappe.throw(_("Only an authorised HR recovery operator can reverse credit."), frappe.PermissionError)
	if not (cint(frappe.conf.get("maintenance_mode")) and cint(frappe.conf.get("pause_scheduler"))):
		frappe.throw(
			_("Recovery requires maintenance mode, paused scheduler and drained workers."),
			frappe.PermissionError,
		)
	_require(
		isinstance(reason, str) and 0 < len(reason.strip()) <= 1000,
		"Provide a recovery reason within 1,000 characters.",
	)
	point = "comp_off_recovery_" + frappe.generate_hash(length=10)
	frappe.db.savepoint(point)
	try:
		return _reverse(name, reason.strip(), actor)
	except Exception:
		frappe.db.rollback(save_point=point)
		raise


def _reverse(name, reason, actor):
	from hrms.api import comp_off

	employee = frappe.db.get_value(comp_off.DOCTYPE, name, "employee")
	_require(bool(employee), "The credit request does not exist.")
	comp_off._lock_employee(employee)
	frappe.db.sql("select name from `tabCompensatory Leave Request` where name=%s for update", name)
	doc = frappe.get_doc(comp_off.DOCTYPE, name)
	_require(
		doc.employee == employee
		and doc.portal_request
		and doc.portal_status == "Approved"
		and doc.docstatus in (1, 2)
		and doc.leave_type == comp_off.LEAVE_TYPE
		and doc.work_from_date == doc.work_end_date
		and bool(doc.leave_allocation),
		"Only an approved single-day portal credit can be recovered.",
	)
	frappe.db.sql("select name from `tabLeave Allocation` where name=%s for update", doc.leave_allocation)
	allocation = frappe.get_doc("Leave Allocation", doc.leave_allocation)
	_require(
		allocation.docstatus == 1
		and allocation.employee == employee
		and allocation.leave_type == comp_off.LEAVE_TYPE,
		"The linked allocation does not match this credit.",
	)
	before = _snapshot(allocation)
	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": comp_off.DOCTYPE,
			"reference_name": name,
			"comment_type": "Comment",
			"content": ["like", "%" + MARKER + "%"],
		},
		fields=["content"],
	)
	if doc.docstatus == 2:
		_require(len(comments) == 1, "Cancelled credit has no unique recovery audit record.")
		try:
			audit = json.loads(html.unescape(comments[0].content))
		except (ValueError, TypeError):
			frappe.throw(_("Recovery audit is unreadable; manual investigation is required."))
		_require(
			audit.get("marker") == MARKER
			and audit.get("request") == name
			and audit.get("allocation") == allocation.name
			and audit.get("after") == before,
			"Recovery state has changed; manual investigation is required.",
		)
		return {"name": name, "status": "Cancelled", "leave_allocation": allocation.name}
	_require(not comments, "This credit already has a recovery audit record.")
	_require(
		not any(cint(allocation.get(field)) for field in ("expired", "carry_forward"))
		and not any(
			flt(allocation.get(field)) for field in ("unused_leaves", "carry_forwarded_leaves_count")
		),
		"Expired or carried-forward allocations require manual investigation.",
	)
	period = (employee, comp_off.LEAVE_TYPE, allocation.to_date, allocation.from_date)
	applications = frappe.db.sql(
		"select name from `tabLeave Application` where employee=%s and leave_type=%s "
		"and from_date<=%s and to_date>=%s and docstatus<2 "
		"and status not in ('Rejected', 'Cancelled') for update",
		period,
	)
	_require(not applications, "This allocation has leave requests; recovery requires manual investigation.")
	period_rows = frappe.db.sql(
		f"select {LEDGER_FIELDS} from `tabLeave Ledger Entry` where employee=%s and leave_type=%s "
		"and from_date<=%s and to_date>=%s and docstatus=1 order by name for update",
		period,
		as_dict=True,
	)
	_require(
		all(
			row.transaction_type == "Leave Allocation"
			and flt(row.leaves) >= 0
			and not row.is_expired
			and not row.is_carry_forward
			for row in period_rows
		),
		"Leave use, adjustment, expiry or prior reversal requires manual investigation.",
	)
	later = frappe.db.sql(
		"select name from `tabLeave Allocation` where employee=%s and leave_type=%s "
		"and from_date>%s and docstatus<2 and carry_forward=1 for update",
		(employee, comp_off.LEAVE_TYPE, allocation.from_date),
	)
	_require(not later, "A later carry-forward allocation requires manual investigation.")
	credit = 0.5 if cint(doc.half_day) else 1.0
	_require(
		before["new"] >= credit
		and before["total"] >= credit
		and abs(before["ledger_total"] - before["new"]) < 0.000001,
		"Allocation and ledger totals do not reconcile.",
	)
	doc.flags.ignore_permissions = True
	with comp_off._operation(doc, "recover"):
		doc.cancel()
	after = _snapshot(allocation)
	old = {row["name"]: row for row in before["rows"]}
	current = {row["name"]: row for row in after["rows"]}
	new = [row for key, row in current.items() if key not in old]
	_require(
		doc.docstatus == 2
		and all(current.get(key) == row for key, row in old.items())
		and len(new) == 1
		and new[0]["docstatus"] == 1
		and flt(new[0]["leaves"]) == -credit
		and getdate(new[0]["from_date"]) == getdate(add_days(doc.work_end_date, 1))
		and getdate(new[0]["to_date"]) == getdate(allocation.to_date)
		and not new[0]["is_expired"]
		and not new[0]["is_carry_forward"]
		and all(
			abs(after[key] - (before[key] - credit)) < 0.000001 for key in ("new", "total", "ledger_total")
		),
		"Native recovery did not produce the exact expected reversal; changes were rolled back.",
	)
	audit = {
		"marker": MARKER,
		"actor": actor,
		"reason": reason,
		"request": name,
		"allocation": allocation.name,
		"credit": credit,
		"before": before,
		"after": after,
	}
	doc.add_comment("Comment", html.escape(json.dumps(audit, sort_keys=True)))
	return {"name": name, "status": "Cancelled", "leave_allocation": allocation.name}
