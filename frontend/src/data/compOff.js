import { createResource } from "frappe-ui"

export const compOffContext = createResource({
	url: "hrms.api.comp_off.get_context",
	auto: false,
	cache: "hrms:comp_off_context",
})

export const compOffRequests = createResource({
	url: "hrms.api.comp_off.get_requests",
	auto: false,
})

export const createCompOffRequest = createResource({
	url: "hrms.api.comp_off.create_request",
	auto: false,
})

export const decideCompOffRequest = createResource({
	url: "hrms.api.comp_off.decide_request",
	auto: false,
})

export const bootEnablesCompOff = () =>
	window.frappe?.boot?.comp_off_self_service === true ||
	window.frappe?.boot?.comp_off_self_service === 1
