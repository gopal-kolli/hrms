# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_link_to_form, getdate

from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry
from hrms.hr.utils import get_leave_period


class LeaveAdjustment(Document):
	def before_validate(self):
		system_precision = cint(frappe.db.get_single_value("System Settings", "float_precision")) or 3
		precision = self.precision("leaves_to_adjust") or system_precision
		self.leaves_to_adjust = flt(self.leaves_to_adjust, precision)

	def set_leaves_after_adjustment(self):
		if self.adjustment_type == "Allocate":
			self.leaves_after_adjustment = flt(self.allocated_leaves) + flt(self.leaves_to_adjust)
		elif self.adjustment_type == "Reduce":
			self.leaves_after_adjustment = flt(self.allocated_leaves) - flt(self.leaves_to_adjust)

	def validate(self):
		self.validate_posting_date()
		self.validate_duplicate_leave_adjustment()
		self.validate_non_zero_adjustment()
		self.validate_over_allocation()
		self.validate_leave_balance()
		# Direct submit runs validate but does not run the draft-only before_save.
		# Persist the derived value for both Desk save/submit and API submissions.
		self.set_leaves_after_adjustment()

	def validate_posting_date(self):
		# Serialize adjustments to this allocation, including separate credit dates.
		# The following ledger/duplicate queries use locking reads so a transaction
		# which waited here cannot validate against an older database snapshot.
		allocation = self.lock_allocation()
		if allocation.docstatus != 1:
			frappe.throw(_("The selected leave allocation must be submitted."))
		if allocation.employee != self.employee or allocation.leave_type != self.leave_type:
			frappe.throw(_("Employee and Leave Type must match the selected leave allocation."))
		self.validate_unexpired_allocation(allocation)

		# Resolve fetched fields on the server for Desk, REST and console callers.
		self.from_date = allocation.from_date
		self.to_date = allocation.to_date
		if not self.posting_date or not getdate(self.from_date) <= getdate(self.posting_date) <= getdate(
			self.to_date
		):
			frappe.throw(_("Posting Date must be within the selected leave allocation period."))
		self.allocated_leaves = self.entitlement_on(self.posting_date)

	def lock_allocation(self):
		rows = frappe.db.sql(
			"""select name, docstatus, employee, leave_type, from_date, to_date, expired
			from `tabLeave Allocation` where name=%s for update""",
			self.leave_allocation,
			as_dict=True,
		)
		if not rows:
			frappe.throw(_("The selected leave allocation does not exist."), frappe.DoesNotExistError)
		return rows[0]

	def validate_unexpired_allocation(self, allocation):
		# A previously calculated expiry entry must not become stale through a
		# later correction or cancellation. Expiry recovery is a separate workflow.
		expiry = frappe.db.sql(
			"""select name from `tabLeave Ledger Entry`
			where transaction_type='Leave Allocation' and transaction_name=%s
			and docstatus=1 and is_expired=1 and is_carry_forward=0 limit 1 for update""",
			self.leave_allocation,
		)
		if allocation.expired or expiry:
			frappe.throw(_("An expired leave allocation cannot be adjusted."))

	def entitlement_entries(self):
		"""Original entitlement plus dated corrections; consumption never frees cap.

		Carry-forward entitlement retains its native allocation-cap treatment.
		Expiry and application rows are not grants. Exclude this document so the
		comparison also works before cancelling a submitted adjustment.
		"""
		return frappe.db.sql(
			"""select ledger.from_date, ledger.leaves
			from `tabLeave Ledger Entry` ledger
			left join `tabLeave Adjustment` adjustment
			  on ledger.transaction_type='Leave Adjustment'
			  and adjustment.name=ledger.transaction_name
			where ledger.docstatus=1 and ledger.is_expired=0 and ledger.is_lwp=0
			  and ledger.employee=%s and ledger.leave_type=%s
			  and (
			    (ledger.transaction_type='Leave Allocation' and ledger.transaction_name=%s)
			    or (adjustment.docstatus=1 and adjustment.leave_allocation=%s
			        and adjustment.name!=%s)
			  )
			order by ledger.from_date, ledger.name for update""",
			(self.employee, self.leave_type, self.leave_allocation, self.leave_allocation, self.name or ""),
			as_dict=True,
		)

	def entitlement_on(self, date):
		return flt(
			sum(
				flt(row.leaves)
				for row in self.entitlement_entries()
				if getdate(row.from_date) <= getdate(date)
			)
		)

	def validate_duplicate_leave_adjustment(self):
		duplicate_adjustment = frappe.db.sql(
			"""select name from `tabLeave Adjustment`
			where leave_allocation=%s and posting_date=%s and docstatus=1 and name!=%s
			limit 1 for update""",
			(self.leave_allocation, self.posting_date, self.name or ""),
		)
		if duplicate_adjustment:
			frappe.throw(
				title=_("Duplicate Leave Adjustment"),
				msg=_("Leave Adjustment for this allocation and posting date already exists: {0}.").format(
					get_link_to_form("Leave Adjustment", duplicate_adjustment[0][0])
				),
			)

	def validate_non_zero_adjustment(self):
		if self.leaves_to_adjust == 0:
			frappe.throw(_("Enter a non-zero value to adjust."))

	def validate_over_allocation(self):
		amount = flt(self.leaves_to_adjust)
		self.validate_entitlement_cap(amount if self.adjustment_type == "Allocate" else -amount)

	def validate_entitlement_cap(self, added_leaves):
		"""Keep each affected entitlement checkpoint within zero and the cap."""

		max_leaves_allowed = frappe.db.get_value("Leave Type", self.leave_type, "max_leaves_allowed")
		entries = self.entitlement_entries()
		posting_date = getdate(self.posting_date)
		entitlement = sum(flt(row.leaves) for row in entries if getdate(row.from_date) <= posting_date)
		maximum = minimum = entitlement
		# Aggregate same-day changes before checking that day's effective entitlement.
		future = {}
		for row in entries:
			date = getdate(row.from_date)
			if date > posting_date:
				future[date] = future.get(date, 0) + flt(row.leaves)
		for date in sorted(future):
			entitlement += future[date]
			maximum = max(maximum, entitlement)
			minimum = min(minimum, entitlement)
		precision = self.precision("leaves_to_adjust") or 3
		if flt(minimum + added_leaves, precision) < 0:
			frappe.throw(_("The adjustment would make allocated leave entitlement negative."))
		sibling_total = self.sibling_allocation_total() if max_leaves_allowed else 0
		if max_leaves_allowed and flt(maximum + added_leaves + sibling_total, precision) > max_leaves_allowed:
			frappe.throw(
				_("Allocation is greater than the maximum allowed {0} for leave type {1}").format(
					frappe.bold(max_leaves_allowed), frappe.bold(self.leave_type)
				)
			)

	def sibling_allocation_total(self):
		"""Retain the native cap across allocations in the same Leave Period.

		An earlier allocation's consumption or expiry does not create new annual
		capacity. Use the same overlap and parent-total semantics as allocation
		validation, with a current locking read for competing adjustments.
		"""
		company = frappe.db.get_value("Employee", self.employee, "company")
		periods = get_leave_period(self.from_date, self.to_date, company)
		if not periods:
			return 0
		period = periods[0]
		rows = frappe.db.sql(
			"""select total_leaves_allocated from `tabLeave Allocation`
			where employee=%s and leave_type=%s and docstatus=1 and name!=%s
			and from_date<=%s and to_date>=%s order by name for update""",
			(self.employee, self.leave_type, self.leave_allocation, period.to_date, period.from_date),
			as_dict=True,
		)
		return sum(flt(row.total_leaves_allocated) for row in rows)

	def validate_leave_balance(self):
		if self.adjustment_type == "Allocate":
			return

		leave_balance = get_leave_balance_on(
			employee=self.employee, leave_type=self.leave_type, date=self.posting_date
		)

		if leave_balance < self.leaves_to_adjust:
			frappe.throw(
				_("Reduction is more than {0}'s available leave balance {1} for leave type {2}").format(
					frappe.bold(self.employee_name), frappe.bold(leave_balance), frappe.bold(self.leave_type)
				)
			)

	def on_submit(self):
		self.create_leave_ledger_entry(submit=True)

	def before_cancel(self):
		allocation = self.lock_allocation()
		self.validate_unexpired_allocation(allocation)
		# The query excludes this document: simulate its removal, preserving both
		# the cap and the entitlement required by later dated reductions.
		self.validate_entitlement_cap(0)

	def on_cancel(self):
		self.create_leave_ledger_entry(submit=False)

	def create_leave_ledger_entry(self, submit):
		is_lwp = frappe.db.get_value("Leave Type", self.leave_type, "is_lwp")

		args = dict(
			leaves=self.leaves_to_adjust
			if self.adjustment_type == "Allocate"
			else (-1 * self.leaves_to_adjust),
			# Allocation dates describe the available period; the correction only
			# becomes effective on its posting date. Existing ledger rows are untouched.
			from_date=self.posting_date,
			to_date=self.to_date,
			is_lwp=is_lwp,
		)
		create_leave_ledger_entry(self, args, submit)


@frappe.whitelist()
def get_leave_allocation_for_posting_date(
	employee: str, leave_type: str, posting_date: str | datetime.date
) -> list[dict]:
	"""
	Returns the leave allocation for the given employee, leave type and posting date.
	"""
	return frappe.get_list(
		"Leave Allocation",
		{
			"employee": employee,
			"leave_type": leave_type,
			"from_date": ["<=", posting_date],
			"to_date": [">=", posting_date],
			"docstatus": 1,
		},
		["name"],
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_allocated_leave_types(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict
) -> tuple[tuple[str, str]]:
	"""
	Returns the leave types allocated to the given employee
	"""
	return frappe.get_list(
		"Leave Allocation",
		{
			"employee": filters.get("employee"),
			"docstatus": 1,
		},
		[
			"leave_type",
			"name",
		],
		as_list=1,
	)
