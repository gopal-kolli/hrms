"""Add missing personal-detail storage only; preserve existing custom definitions/values."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	definitions = [
		("custom_bank_account_holder", "Bank account holder", "Data", None),
		("custom_aadhaar_number", "Aadhaar Number", "Data", None),
		("custom_city", "City", "Data", None),
		("custom_state", "State", "Data", None),
		("custom_pin_code", "PIN code", "Data", None),
		("custom_pf_nominee_name", "PF nominee name", "Data", None),
		(
			"custom_pf_nominee_relation",
			"PF nominee relationship",
			"Select",
			"Spouse\nFather\nMother\nSon\nDaughter\nBrother\nSister\nOther",
		),
		("custom_pf_nominee_dob", "PF nominee date of birth", "Date", None),
	]
	meta = frappe.get_meta("Employee")
	missing = [
		dict(
			fieldname=key, label=label, fieldtype=kind, options=options, insert_after="bank_ac_no", no_copy=1
		)
		for key, label, kind, options in definitions
		if not meta.has_field(key)
	]
	if missing:
		create_custom_fields({"Employee": missing}, update=False)
