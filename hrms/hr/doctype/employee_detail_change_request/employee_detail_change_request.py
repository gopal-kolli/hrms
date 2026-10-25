from frappe.model.document import Document

from hrms.api.my_details import guard_write


class EmployeeDetailChangeRequest(Document):
	before_insert = guard_write
	before_validate = guard_write
	on_trash = guard_write
