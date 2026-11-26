"""Create the opt-in portal approver role without assigning any users."""

from hrms.setup import create_comp_off_approver_role


def execute():
	create_comp_off_approver_role()
