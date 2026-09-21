# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, add_to_date, get_first_day, get_last_day, getdate

from hrms.hr.doctype.leave_allocation.test_leave_allocation import (
	create_leave_allocation,
	process_expired_allocation,
)
from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
from hrms.hr.doctype.leave_type.test_leave_type import create_leave_type
from hrms.payroll.doctype.salary_slip.test_salary_slip import make_leave_application
from hrms.tests.utils import HRMSTestSuite


class TestLeaveAdjustment(HRMSTestSuite):
	def setUp(self):
		self.employee = frappe.get_doc("Employee", {"first_name": "_Test Employee"})
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
