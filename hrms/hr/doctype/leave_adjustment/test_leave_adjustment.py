# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

import frappe
from frappe.utils import add_days, add_months, add_to_date, get_first_day, get_last_day, getdate, nowdate

from hrms.hr.doctype.leave_allocation.test_leave_allocation import (
	create_leave_allocation,
	process_expired_allocation,
)
from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry
from hrms.hr.doctype.leave_type.test_leave_type import create_leave_type
from hrms.payroll.doctype.salary_slip.test_salary_slip import make_leave_application
from hrms.tests.utils import HRMSTestSuite


class TestLeaveAdjustment(HRMSTestSuite):
	def setUp(self):
		self.employee = frappe.get_doc("Employee", {"first_name": "_Test Employee"})
		if self._testMethodName.startswith("test_concurrent_"):
			# Each concurrency scenario commits its own uniquely named allocation
			# for separate DB connections. Do not also persist the shared ordinary
			# test allocation across the CI commands for those scenarios.
			return
		self.leave_allocation = create_leave_allocation(
			employee=self.employee.name,
			employee_name=self.employee.employee_name,
			leave_type="_Test Leave Type",
			new_leaves_allocated=10,
			from_date=get_first_day(getdate()),
			to_date=get_last_day(getdate()),
		)
		self.leave_allocation.submit()

	def test_duplicate_leave_adjustment(self):
		create_leave_adjustment(self.leave_allocation, adjustment_type="Reduce", leaves_to_adjust=3).submit()
		duplicate_adjustment = create_leave_adjustment(
			self.leave_allocation, adjustment_type="Allocate", leaves_to_adjust=10
		)
		self.assertRaises(frappe.ValidationError, duplicate_adjustment.save)

	def test_adjustment_is_effective_only_from_posting_date(self):
		posting_date = add_days(self.leave_allocation.from_date, 10)
		prior_date = add_days(posting_date, -1)
		for adjustment_type, amount, expected in [("Allocate", 2.75, 12.75), ("Reduce", 3.75, 6.25)]:
			with self.subTest(adjustment_type=adjustment_type):
				adjustment = create_leave_adjustment(
					self.leave_allocation,
					adjustment_type=adjustment_type,
					leaves_to_adjust=amount,
					posting_date=posting_date,
				).submit()
				for date, balance in [
					(prior_date, 10),
					(posting_date, expected),
					(self.leave_allocation.to_date, expected),
				]:
					self.assertEqual(
						get_leave_balance_on(self.employee.name, "_Test Leave Type", date), balance
					)
				ledger = frappe.get_doc("Leave Ledger Entry", {"transaction_name": adjustment.name})
				self.assertEqual(getdate(ledger.from_date), getdate(posting_date))
				self.assertEqual(getdate(ledger.to_date), getdate(self.leave_allocation.to_date))
				self.assertEqual(
					frappe.db.count("Leave Ledger Entry", {"transaction_name": adjustment.name}), 1
				)
				adjustment.cancel()
				self.assertEqual(
					get_leave_balance_on(self.employee.name, "_Test Leave Type", posting_date), 10
				)

	def test_posting_date_must_be_within_allocation(self):
		for posting_date in [
			add_days(self.leave_allocation.from_date, -1),
			add_days(self.leave_allocation.to_date, 1),
		]:
			with self.subTest(posting_date=posting_date):
				adjustment = create_leave_adjustment(
					self.leave_allocation,
					adjustment_type="Allocate",
					leaves_to_adjust=1,
					posting_date=posting_date,
				)
				self.assertRaises(frappe.ValidationError, adjustment.save)

	def test_allocation_fields_are_authoritative(self):
		adjustment = create_leave_adjustment(
			self.leave_allocation, adjustment_type="Allocate", leaves_to_adjust=1
		)
		adjustment.from_date = add_days(self.leave_allocation.from_date, -30)
		adjustment.to_date = add_days(self.leave_allocation.to_date, 30)
		adjustment.allocated_leaves = 0
		adjustment.validate_posting_date()
		self.assertEqual(getdate(adjustment.from_date), getdate(self.leave_allocation.from_date))
		self.assertEqual(getdate(adjustment.to_date), getdate(self.leave_allocation.to_date))
		self.assertEqual(adjustment.allocated_leaves, 10)
		adjustment.leave_type = "Unrelated Leave Type"
		self.assertRaises(frappe.ValidationError, adjustment.validate_posting_date)
		adjustment.leave_type = self.leave_allocation.leave_type
		adjustment.employee = "Unrelated Employee"
		self.assertRaises(frappe.ValidationError, adjustment.validate_posting_date)

	def test_report_excludes_adjustment_before_posting_date(self):
		from hrms.hr.report.employee_leave_balance.employee_leave_balance import get_data

		posting_date = add_days(self.leave_allocation.from_date, 10)

		def report(from_date, to_date):
			rows = get_data(frappe._dict(from_date=from_date, to_date=to_date, employee=self.employee.name))
			return next(row for row in rows if row.get("leave_type") == "_Test Leave Type")

		before = report(self.leave_allocation.from_date, add_days(posting_date, -1))
		for adjustment_type, amount, signed in [("Allocate", 2.75, 2.75), ("Reduce", 3.75, -3.75)]:
			with self.subTest(adjustment_type=adjustment_type):
				adjustment = create_leave_adjustment(
					self.leave_allocation,
					adjustment_type=adjustment_type,
					leaves_to_adjust=amount,
					posting_date=posting_date,
				).submit()
				self.assertEqual(report(self.leave_allocation.from_date, add_days(posting_date, -1)), before)
				current = report(posting_date, self.leave_allocation.to_date)
				self.assertEqual(current.opening_balance, 10)
				self.assertEqual(current.leaves_allocated, signed)
				self.assertEqual(current.closing_balance, 10 + signed)
				adjustment.cancel()

	def test_adjustment_for_over_allocation(self):
		leave_type = create_leave_type(leave_type_name="Test Over Allocation", max_leaves_allowed=30)
		leave_allocation = create_leave_allocation(
			employee=self.employee.name,
			employee_name=self.employee.employee_name,
			leave_type=leave_type.name,
			new_leaves_allocated=25,
		)
		leave_allocation.submit()
		leave_adjustment = create_leave_adjustment(
			leave_allocation, adjustment_type="Allocate", leaves_to_adjust=10
		)

		self.assertRaises(frappe.ValidationError, leave_adjustment.save)

	def test_adjustment_for_negative_leave_balance(self):
		make_leave_application(
			employee=self.employee.name,
			from_date=get_first_day(getdate()),
			to_date=add_days(get_first_day(getdate()), 6),
			leave_type="_Test Leave Type",
		)

		leave_adjustment = create_leave_adjustment(
			self.leave_allocation,
			adjustment_type="Reduce",
			leaves_to_adjust=5,
			posting_date=add_days(get_first_day(getdate()), 20),
		)

		self.assertRaises(frappe.ValidationError, leave_adjustment.save)

	def test_increase_balance_with_adjustment(self):
		create_leave_adjustment(
			self.leave_allocation, adjustment_type="Allocate", leaves_to_adjust=6
		).submit()

		leave_balance = get_leave_balance_on(
			employee=self.employee.name, leave_type="_Test Leave Type", date=getdate()
		)

		self.assertEqual(leave_balance, 16)

	def test_decrease_balance_with_adjustment(self):
		create_leave_adjustment(self.leave_allocation, adjustment_type="Reduce", leaves_to_adjust=3).submit()
		leave_balance = get_leave_balance_on(
			employee=self.employee.name, leave_type="_Test Leave Type", date=getdate()
		)
		self.assertEqual(leave_balance, 7)

	def test_decrease_balance_after_leave_is_applied(self):
		# allocation of 10 leaves, leave application for 3 days
		mid_month = add_days(get_first_day(getdate()), 15)
		make_leave_application(
			employee=self.employee.name,
			from_date=mid_month,
			to_date=add_days(mid_month, 2),
			leave_type="_Test Leave Type",
		)
		# adjustment of 6 days made after applications
		create_leave_adjustment(
			self.leave_allocation,
			adjustment_type="Allocate",
			leaves_to_adjust=6,
			posting_date=get_last_day(getdate()),
		).submit()
		# so total balance should be 10 - 3 + 6 = 13
		leave_balance = get_leave_balance_on(
			employee=self.employee.name, leave_type="_Test Leave Type", date=get_last_day(getdate())
		)
		self.assertEqual(leave_balance, 13)

	@HRMSTestSuite.change_settings("System Settings", {"float_precision": 2})
	def test_precision(self):
		leave_adjustment = create_leave_adjustment(
			self.leave_allocation, adjustment_type="Allocate", leaves_to_adjust=5.126
		)
		leave_adjustment.submit()
		leave_adjustment.reload()
		self.assertEqual(leave_adjustment.leaves_to_adjust, 5.13)

	def test_back_dated_leave_adjustment(self):
		for dt in ["Leave Allocation", "Leave Ledger Entry"]:
			frappe.db.delete(dt)

		# backdated leave allocation
		leave_allocation = create_leave_allocation(
			employee=self.employee.name,
			employee_name=self.employee.employee_name,
			leave_type="_Test Leave Type",
			from_date=add_to_date(getdate(), months=-13),
			to_date=add_to_date(getdate(), months=-1),
			new_leaves_allocated=10,
		)
		leave_allocation.submit()
		# backdated leave adjustment
		create_leave_adjustment(
			leave_allocation,
			adjustment_type="Reduce",
			leaves_to_adjust=5,
			posting_date=add_to_date(getdate(), months=-10),
		).submit()
		# leave balance in previous period
		leave_balance = get_leave_balance_on(
			employee=self.employee.name,
			leave_type="_Test Leave Type",
			date=add_to_date(getdate(), months=-1),
		)
		self.assertEqual(leave_balance, 5.0)
		# leave balance now, should be 0 because everything has expired
		leave_balance = get_leave_balance_on(
			employee=self.employee.name, leave_type="_Test Leave Type", date=getdate()
		)
		self.assertEqual(leave_balance, 0.0)

	def test_reduction_type_adjustment_while_carry_forwarding_leaves(self):
		for dt in ["Leave Allocation", "Leave Ledger Entry"]:
			frappe.db.delete(dt)

		leave_type = create_leave_type(leave_type_name="CF Adjustment", is_carry_forward=1)
		leave_allocation = create_leave_allocation(
			employee=self.employee.name,
			employee_name=self.employee.employee_name,
			leave_type=leave_type.name,
			from_date=add_to_date(getdate(), months=-13),
			to_date=add_to_date(getdate(), months=-1),
			new_leaves_allocated=10,
		)
		leave_allocation.submit()
		create_leave_adjustment(
			leave_allocation,
			adjustment_type="Reduce",
			leaves_to_adjust=5,
			posting_date=add_to_date(getdate(), months=-10),
		).submit()

		create_leave_allocation(
			employee=self.employee.name,
			employee_name=self.employee.employee_name,
			leave_type=leave_type.name,
			from_date=add_to_date(getdate(), days=-15),
			to_date=getdate(),
			new_leaves_allocated=10,
			carry_forward=1,
		).submit()
		leave_balance = get_leave_balance_on(
			employee=self.employee.name, leave_type=leave_type.name, date=getdate()
		)

		# 5 carried forward + 10 new
		self.assertEqual(leave_balance, 15.0)

	def test_allocate_type_adjustment_while_carry_forwarding_leaves(self):
		for dt in ["Leave Allocation", "Leave Ledger Entry"]:
			frappe.db.delete(dt)

		leave_type = create_leave_type(leave_type_name="CF Adjustment", is_carry_forward=1)
		leave_allocation = create_leave_allocation(
			employee=self.employee.name,
			employee_name=self.employee.employee_name,
			leave_type=leave_type.name,
			from_date=add_to_date(getdate(), months=-13),
			to_date=add_to_date(getdate(), months=-1),
			new_leaves_allocated=10,
		)
		leave_allocation.submit()
		create_leave_adjustment(
			leave_allocation,
			adjustment_type="Allocate",
			leaves_to_adjust=5,
			posting_date=add_to_date(getdate(), months=-10),
		).submit()

		create_leave_allocation(
			employee=self.employee.name,
			employee_name=self.employee.employee_name,
			leave_type=leave_type.name,
			from_date=add_to_date(getdate(), days=-25),
			to_date=getdate(),
			new_leaves_allocated=5,
			carry_forward=1,
		).submit()
		leave_balance = get_leave_balance_on(
			employee=self.employee.name, leave_type=leave_type.name, date=getdate()
		)

		# 15 carried forward + 5 new
		self.assertEqual(leave_balance, 20.0)

	def test_allows_one_adjustment_per_allocation_and_posting_date(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=0)
		september = allocation.from_date
		october = add_months(september, 1)

		create_leave_adjustment(allocation, "Allocate", 0.6, september).submit()
		create_leave_adjustment(allocation, "Allocate", 0.6, october).submit()

		duplicate = create_leave_adjustment(allocation, "Allocate", 0.6, september)
		self.assertRaises(frappe.ValidationError, duplicate.save)

	def test_monthly_credits_are_effective_from_each_posting_date(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=0)
		posting_dates = [add_months(allocation.from_date, month) for month in range(4)]

		adjustments = [
			create_leave_adjustment(allocation, "Allocate", 0.6, posting_date).submit()
			for posting_date in posting_dates
		]

		self.assertEqual(
			get_leave_balance_on(
				self.employee.name, allocation.leave_type, add_days(allocation.from_date, -1)
			),
			0,
		)
		for expected, posting_date in zip([0.6, 1.2, 1.8, 2.4], posting_dates, strict=True):
			self.assertAlmostEqual(
				get_leave_balance_on(self.employee.name, allocation.leave_type, posting_date),
				expected,
			)
		self.assertEqual(
			get_leave_balance_on(self.employee.name, allocation.leave_type, allocation.to_date), 2.4
		)
		self.assertEqual(
			frappe.db.count(
				"Leave Ledger Entry",
				{"transaction_type": "Leave Adjustment", "leave_type": allocation.leave_type},
			),
			4,
		)
		for adjustment, posting_date in zip(adjustments, posting_dates, strict=True):
			ledger = frappe.get_doc("Leave Ledger Entry", {"transaction_name": adjustment.name})
			self.assertEqual(getdate(ledger.from_date), getdate(posting_date))

	def test_adjustment_entitlement_is_authoritative_not_consumed_balance(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=10, max_leaves_allowed=12)
		first_date = allocation.from_date
		second_date = add_months(first_date, 1)
		create_leave_adjustment(allocation, "Reduce", 4, first_date).submit()
		make_leave_application(
			employee=self.employee.name,
			from_date=add_days(first_date, 1),
			to_date=add_days(first_date, 2),
			leave_type=allocation.leave_type,
		)

		credit = create_leave_adjustment(allocation, "Allocate", 0.6, second_date).submit()
		credit.reload()
		self.assertEqual(credit.allocated_leaves, 6)
		self.assertEqual(credit.leaves_after_adjustment, 6.6)

	def test_reductions_allow_monthly_credit_below_maximum_entitlement(self):
		for reduction, expected_entitlement in [(12, 0), (6, 6)]:
			with self.subTest(reduction=reduction):
				allocation = self.make_monthly_allocation(new_leaves_allocated=12, max_leaves_allowed=12)
				create_leave_adjustment(allocation, "Reduce", reduction, allocation.from_date).submit()
				credit = create_leave_adjustment(
					allocation, "Allocate", 0.6, add_months(allocation.from_date, 1)
				).submit()
				credit.reload()
				self.assertEqual(credit.allocated_leaves, expected_entitlement)
				self.assertEqual(credit.leaves_after_adjustment, expected_entitlement + 0.6)

	def test_consumption_does_not_reopen_monthly_credit_cap(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=10, max_leaves_allowed=12)
		first_date = allocation.from_date
		create_leave_adjustment(allocation, "Allocate", 2, first_date).submit()
		make_leave_application(
			employee=self.employee.name,
			from_date=add_days(first_date, 1),
			to_date=add_days(first_date, 3),
			leave_type=allocation.leave_type,
		)

		credit = create_leave_adjustment(allocation, "Allocate", 0.6, add_months(first_date, 1))
		self.assertRaises(frappe.ValidationError, credit.save)

	def test_backdated_credit_cannot_breach_a_later_committed_credit_cap(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=10, max_leaves_allowed=12)
		september = allocation.from_date
		december = add_months(september, 3)
		create_leave_adjustment(allocation, "Allocate", 0.6, december).submit()

		backdated_credit = create_leave_adjustment(allocation, "Allocate", 1.6, september)
		self.assertRaises(frappe.ValidationError, backdated_credit.save)

	def test_non_overlapping_sibling_allocation_in_leave_period_counts_toward_cap(self):
		period_start, period_end = getdate("2030-01-01"), getdate("2030-12-31")
		frappe.get_doc(
			{
				"doctype": "Leave Period",
				"name": f"Test Monthly Adjustment Period {uuid.uuid4().hex}",
				"company": "_Test Company",
				"from_date": period_start,
				"to_date": period_end,
				"is_active": 1,
			}
		).insert()
		leave_type = create_leave_type(
			leave_type_name=f"Test Monthly Cap Sibling {uuid.uuid4().hex}", max_leaves_allowed=12
		)
		self.make_allocation_for_type(leave_type.name, period_start, getdate("2030-06-30"), 6)
		current = self.make_allocation_for_type(leave_type.name, getdate("2030-07-01"), period_end, 5)

		credit = create_leave_adjustment(current, "Allocate", 2, getdate("2030-07-01"))
		self.assertRaises(frappe.ValidationError, credit.save)

	def test_backdated_reduction_cannot_make_later_entitlement_negative(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=10)
		september = allocation.from_date
		december = add_months(september, 3)
		create_leave_adjustment(allocation, "Reduce", 8, december).submit()

		backdated_reduction = create_leave_adjustment(allocation, "Reduce", 3, september)
		self.assertRaises(frappe.ValidationError, backdated_reduction.save)

	def test_cancelling_reduction_cannot_reopen_a_later_cap_breach(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=12, max_leaves_allowed=12)
		reduction = create_leave_adjustment(allocation, "Reduce", 2, allocation.from_date).submit()
		create_leave_adjustment(allocation, "Allocate", 0.6, add_months(allocation.from_date, 1)).submit()

		self.assertRaises(frappe.ValidationError, reduction.cancel)
		reduction.reload()
		self.assertEqual(reduction.docstatus, 1)

	def test_cancelling_monthly_credit_keeps_other_dated_credits(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=0)
		september = allocation.from_date
		october = add_months(september, 1)
		september_credit = create_leave_adjustment(allocation, "Allocate", 0.6, september).submit()
		october_credit = create_leave_adjustment(allocation, "Allocate", 0.6, october).submit()

		september_credit.cancel()
		self.assertFalse(frappe.db.exists("Leave Ledger Entry", {"transaction_name": september_credit.name}))
		self.assertTrue(frappe.db.exists("Leave Ledger Entry", {"transaction_name": october_credit.name}))
		self.assertEqual(get_leave_balance_on(self.employee.name, allocation.leave_type, october), 0.6)

	def test_cancelling_credit_cannot_expose_later_negative_entitlement(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=0)
		september = allocation.from_date
		october = add_months(september, 1)
		credit = create_leave_adjustment(allocation, "Allocate", 2, september).submit()
		create_leave_adjustment(allocation, "Reduce", 2, october).submit()

		self.assertRaises(frappe.ValidationError, credit.cancel)
		credit.reload()
		self.assertEqual(credit.docstatus, 1)

	def test_zero_opening_monthly_credits_expire_once_with_the_allocation(self):
		allocation = self.make_monthly_allocation(
			new_leaves_allocated=0,
			from_date=add_months(get_first_day(nowdate()), -5),
			to_date=add_days(get_first_day(nowdate()), -1),
		)
		for month in range(4):
			create_leave_adjustment(
				allocation, "Allocate", 0.6, add_months(allocation.from_date, month)
			).submit()

		process_expired_allocation()
		process_expired_allocation()
		allocation.reload()
		self.assertEqual(allocation.expired, 1)
		self.assertEqual(
			frappe.db.count(
				"Leave Ledger Entry", {"transaction_name": allocation.name, "is_expired": 1, "docstatus": 1}
			),
			1,
		)
		self.assertEqual(get_leave_balance_on(self.employee.name, allocation.leave_type, nowdate()), 0)

	def test_adjustments_cannot_be_created_or_cancelled_after_native_expiry(self):
		allocation = self.make_monthly_allocation(
			new_leaves_allocated=0,
			from_date=add_months(get_first_day(nowdate()), -3),
			to_date=add_days(get_first_day(nowdate()), -1),
		)
		credit = create_leave_adjustment(allocation, "Allocate", 0.6, allocation.from_date).submit()
		process_expired_allocation()

		new_credit = create_leave_adjustment(allocation, "Allocate", 0.6, add_months(allocation.from_date, 1))
		self.assertRaises(frappe.ValidationError, new_credit.save)
		self.assertRaises(frappe.ValidationError, credit.cancel)
		credit.reload()
		self.assertEqual(credit.docstatus, 1)

	def test_carry_forward_expiry_does_not_block_active_non_carry_forward_adjustment(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=10)
		create_leave_ledger_entry(
			allocation,
			{
				"leaves": -1,
				"from_date": allocation.from_date,
				"to_date": allocation.from_date,
				"is_carry_forward": 1,
				"is_expired": 1,
			},
		)

		credit = create_leave_adjustment(allocation, "Allocate", 0.6, add_months(allocation.from_date, 1))
		credit.submit()
		self.assertEqual(credit.docstatus, 1)

	@skipUnless(
		os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("HRMS_CONCURRENCY_ACCEPTANCE") == "1",
		"Separate CI-only concurrent transaction acceptance",
	)
	def test_concurrent_same_date_monthly_credits_submit_exactly_once(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=0)
		result = run_same_date_credit_concurrency(self, allocation.name, allocation.from_date)
		self.assertEqual(result["result"], "PASS")

	@skipUnless(
		os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("HRMS_CONCURRENCY_ACCEPTANCE") == "1",
		"Separate CI-only concurrent transaction acceptance",
	)
	def test_concurrent_credit_and_reduction_cancel_preserve_cap(self):
		allocation = self.make_monthly_allocation(new_leaves_allocated=10, max_leaves_allowed=12)
		reduction = create_leave_adjustment(allocation, "Reduce", 2, allocation.from_date).submit()
		result = run_same_date_credit_concurrency(
			self, allocation.name, add_months(allocation.from_date, 1), cancellation_name=reduction.name
		)
		self.assertEqual(result["result"], "PASS")

	def make_monthly_allocation(
		self, new_leaves_allocated, max_leaves_allowed=None, from_date=None, to_date=None
	):
		"""Create an isolated allocation whose zero opening value is preserved."""
		leave_type = create_leave_type(
			leave_type_name=f"Test Monthly Leave Adjustment {uuid.uuid4().hex}",
			is_earned_leave=new_leaves_allocated == 0,
			max_leaves_allowed=max_leaves_allowed,
		)
		from_date = from_date or get_first_day(nowdate())
		to_date = to_date or add_days(add_months(from_date, 4), -1)
		return frappe.get_doc(
			{
				"doctype": "Leave Allocation",
				"employee": self.employee.name,
				"employee_name": self.employee.employee_name,
				"leave_type": leave_type.name,
				"from_date": from_date,
				"to_date": to_date,
				"new_leaves_allocated": new_leaves_allocated,
			}
		).submit()

	def make_allocation_for_type(self, leave_type, from_date, to_date, new_leaves_allocated):
		return frappe.get_doc(
			{
				"doctype": "Leave Allocation",
				"employee": self.employee.name,
				"employee_name": self.employee.employee_name,
				"leave_type": leave_type,
				"from_date": from_date,
				"to_date": to_date,
				"new_leaves_allocated": new_leaves_allocated,
			}
		).submit()


def create_leave_adjustment(leave_allocation, adjustment_type, leaves_to_adjust=None, posting_date=None):
	leave_adjustment = frappe.new_doc(
		"Leave Adjustment",
		employee=leave_allocation.employee,
		leave_allocation=leave_allocation.name,
		leave_type=leave_allocation.leave_type,
		posting_date=posting_date or getdate(),
		adjustment_type=adjustment_type,
		leaves_to_adjust=leaves_to_adjust or 10,
	)
	return leave_adjustment


def run_same_date_credit_concurrency(case, allocation_name, posting_date, cancellation_name=None):
	"""Exercise two HTTP-like transactions on the disposable GitHub CI database only."""
	if frappe.local.site != "test_site" or os.environ.get("GITHUB_ACTIONS") != "true":
		raise RuntimeError("Concurrency fixture is restricted to disposable GitHub CI")

	frappe.db.commit()  # nosemgrep: make fixture visible to independent CI connections
	site = frappe.local.site
	sites_path = frappe.local.sites_path
	barrier = Barrier(2)

	def submit_credit(index):
		for attempt in range(4):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.flags.in_test = True
				frappe.set_user("Administrator")
				allocation = frappe.get_doc("Leave Allocation", allocation_name)
				if attempt == 0:
					barrier.wait(timeout=30)
				if cancellation_name and index == 1:
					frappe.get_doc("Leave Adjustment", cancellation_name).cancel()
				else:
					create_leave_adjustment(
						allocation, "Allocate", 4 if cancellation_name else 0.6, posting_date
					).submit()
				frappe.db.commit()  # nosemgrep: simulate an independent successful HTTP transaction
				return "submitted"
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
				if attempt == 3:
					raise
			except frappe.ValidationError:
				frappe.db.rollback()
				return "rejected"
			finally:
				frappe.destroy()

	with ThreadPoolExecutor(max_workers=2) as pool:
		outcomes = list(pool.map(submit_credit, range(2)))

	frappe.db.rollback()
	assert outcomes.count("submitted") == 1 and outcomes.count("rejected") == 1, outcomes
	if cancellation_name:
		allocation = frappe.get_doc("Leave Allocation", allocation_name)
		balance = get_leave_balance_on(allocation.employee, allocation.leave_type, posting_date)
		assert balance in (10, 12), balance
		return {"concurrent_create_cancel": 2, "succeeded": 1, "rejected": 1, "result": "PASS"}
	adjustments = frappe.get_all(
		"Leave Adjustment",
		filters={"leave_allocation": allocation_name, "docstatus": 1},
		pluck="name",
	)
	entries = frappe.get_all(
		"Leave Ledger Entry",
		filters={"transaction_name": ["in", adjustments], "docstatus": 1},
		fields=["name", "leaves"],
	)
	assert len(entries) == 1 and entries[0].leaves == 0.6, entries
	return {"concurrent_submissions": 2, "submitted": 1, "rejected": 1, "result": "PASS"}
