<template>
	<BaseLayout>
		<template #body>
			<div class="flex flex-col items-center my-7 p-4 gap-7 max-w-3xl mx-auto">
				<CheckInPanel />
				<LeaveBalance />
				<QuickLinks :items="quickLinks" :title="__('Quick Links')" />
				<RequestPanel />
			</div>
		</template>
	</BaseLayout>
</template>

<script setup>
import { computed, inject, markRaw, onMounted } from "vue"

import CheckInPanel from "@/components/CheckInPanel.vue"
import QuickLinks from "@/components/QuickLinks.vue"
import BaseLayout from "@/components/BaseLayout.vue"
import RequestPanel from "@/components/RequestPanel.vue"
import LeaveBalance from "@/components/LeaveBalance.vue"
import AttendanceIcon from "@/components/icons/AttendanceIcon.vue"
import ShiftIcon from "@/components/icons/ShiftIcon.vue"
import LeaveIcon from "@/components/icons/LeaveIcon.vue"
import ExpenseIcon from "@/components/icons/ExpenseIcon.vue"
import EmployeeAdvanceIcon from "@/components/icons/EmployeeAdvanceIcon.vue"
import SalaryIcon from "@/components/icons/SalaryIcon.vue"
import { bootEnablesCompOff, compOffContext } from "@/data/compOff"

const __ = inject("$translate")

const quickLinks = computed(() => {
	const links = [
		{
			icon: markRaw(AttendanceIcon),
			title: __("Request Attendance"),
			route: "AttendanceRequestFormView",
		},
		{
			icon: markRaw(ShiftIcon),
			title: __("Request a Shift"),
			route: "ShiftRequestFormView",
		},
		{
			icon: markRaw(LeaveIcon),
			title: __("Request Leave"),
			route: "LeaveApplicationFormView",
		},
		{
			icon: markRaw(ExpenseIcon),
			title: __("Claim an Expense"),
			route: "ExpenseClaimFormView",
		},
		{
			icon: markRaw(EmployeeAdvanceIcon),
			title: __("Request an Advance"),
			route: "EmployeeAdvanceFormView",
		},
		{
			icon: markRaw(SalaryIcon),
			title: __("View Salary Slips"),
			route: "SalarySlipsDashboard",
		},
	]

	if (compOffEnabled.value) {
		links.splice(3, 0, {
			icon: markRaw(LeaveIcon),
			title: __("Comp Off"),
			route: "CompOffListView",
		})
	}

	return links
})

const bootFlag = window.frappe?.boot?.comp_off_self_service
const compOffEnabled = computed(
	() => bootEnablesCompOff() || compOffContext.data?.enabled === true
)

onMounted(() => {
	// When older boot data is served, context is the safe fallback. A known-off
	// flag never triggers Comp Off requests.
	if (bootFlag === undefined || bootFlag === null) compOffContext.reload()
})
</script>
