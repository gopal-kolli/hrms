<template>
	<BaseLayout>
		<template #body>
			<main class="home-page">
				<section class="home-intro" aria-labelledby="my-leave-heading">
					<div>
						<h1 id="my-leave-heading">{{ __("My leave") }}</h1>
						<p>{{ employeeName }} <span aria-hidden="true">·</span> {{ today }}</p>
					</div>
					<CheckInPanel v-if="settings.data?.allow_employee_checkin_from_mobile_app" />
				</section>
				<section class="leave-workspace">
					<LeaveBalance />
					<section class="leave-actions" aria-label="Leave actions">
						<router-link
							:to="{ name: 'LeaveApplicationFormView' }"
							class="leave-action leave-action-primary"
							><FeatherIcon name="calendar" class="h-5 w-5" /><span>{{
								__("Request leave")
							}}</span></router-link
						>
						<router-link
							v-if="compOffEnabled"
							:to="{ name: 'CompOffCreateView' }"
							class="leave-action leave-action-secondary"
							><FeatherIcon name="plus-circle" class="h-5 w-5" /><span>{{
								__("Earn comp-off credit")
							}}</span></router-link
						>
					</section>
					<p v-if="compOffEnabled" class="comp-off-hint">
						{{ __("Worked on a holiday? Request manager approval.") }}
					</p>
				</section>
				<section class="mobile-requests request-section" aria-labelledby="mobile-requests-heading">
					<div class="section-heading">
						<h2 id="mobile-requests-heading">{{ __("Your requests") }}</h2>
					</div>
					<p v-if="myLeaves.loading || homeCompOffRequests.loading" class="request-empty">
						{{ __("Loading requests…") }}
					</p>
					<router-link
						v-for="request in recentRequests"
						:key="request.key"
						:to="request.route"
						class="request-row"
					>
						<FeatherIcon :name="request.icon" class="request-icon" />
						<div>
							<strong>{{ request.label }}</strong
							><span>{{ request.date }}</span>
						</div>
						<span class="request-status" :class="request.status?.toLowerCase()">{{
							__(request.status)
						}}</span>
					</router-link>
					<p v-if="myLeaves.error" class="request-empty request-error">
						{{ __("Leave requests could not load. Try leave history.") }}
					</p>
					<p v-else-if="!myLeaves.loading && !myLeaves.data?.length" class="request-empty">
						{{ __("No leave requests yet.") }}
					</p>
					<p
						v-if="compOffEnabled && (compOffError || homeCompOffRequests.error)"
						class="request-empty request-error"
					>
						{{ __("Comp Off requests could not load. Try Comp Off history.") }}
					</p>
					<p
						v-else-if="
							compOffEnabled && !homeCompOffRequests.loading && !homeCompOffRequests.data?.length
						"
						class="request-empty"
					>
						{{ __("No Comp Off credit requests yet.") }}
					</p>
					<nav class="request-history-links" aria-label="Request history">
						<router-link :to="{ name: 'LeaveApplicationListView' }">{{
							__("Leave history")
						}}</router-link>
						<router-link v-if="compOffEnabled" :to="{ name: 'CompOffListView' }">{{
							__("Comp-off history")
						}}</router-link>
						<router-link
							v-if="isManager && compOffEnabled"
							:to="{ name: 'CompOffListView', query: { view: 'approval' } }"
							class="mobile-manager-link"
							:aria-label="__('Review team Comp Off requests')"
							><FeatherIcon name="users" class="h-4 w-4" />{{ __("Team requests") }}</router-link
						>
					</nav>
				</section>
				<section class="home-sections desktop-requests">
					<section class="request-section" aria-labelledby="leave-requests-heading">
						<div class="section-heading">
							<h2 id="leave-requests-heading">{{ __("Your leave requests") }}</h2>
							<router-link :to="{ name: 'LeaveApplicationListView' }" class="portal-text-link">{{
								__("View all")
							}}</router-link>
						</div>
						<div
							v-if="myLeaves.loading"
							class="request-list request-loading"
							:aria-label="__('Loading leave requests')"
						>
							<div v-for="item in 2" :key="item" class="request-loading-row"></div>
						</div>
						<div v-else-if="myLeaves.data?.length" class="request-list">
							<router-link
								v-for="request in myLeaves.data.slice(0, 3)"
								:key="request.name"
								:to="{ name: 'LeaveApplicationDetailView', params: { id: request.name } }"
								class="request-row"
								><div>
									<strong>{{ __(request.leave_type, null, "Leave Type") }}</strong
									><span>{{ request.leave_dates }}</span>
								</div>
								<span class="request-status" :class="request.status?.toLowerCase()">{{
									__(request.status, null, "Leave Application")
								}}</span></router-link
							>
						</div>
						<p v-else-if="myLeaves.error" class="request-empty request-error">
							{{ __("Leave requests could not load. Try again from your leave history.") }}
						</p>
						<p v-else class="request-empty">{{ __("No leave requests yet.") }}</p>
					</section>
					<section
						v-if="compOffEnabled"
						class="request-section"
						aria-labelledby="comp-off-requests-heading"
					>
						<div class="section-heading">
							<h2 id="comp-off-requests-heading">{{ __("Comp Off activity") }}</h2>
							<router-link :to="{ name: 'CompOffListView' }" class="portal-text-link">{{
								__("View all")
							}}</router-link>
						</div>
						<div
							v-if="homeCompOffRequests.loading"
							class="request-list request-loading"
							:aria-label="__('Loading Comp Off requests')"
						>
							<div v-for="item in 2" :key="item" class="request-loading-row"></div>
						</div>
						<div v-else-if="homeCompOffRequests.data?.length" class="request-list">
							<router-link
								v-for="request in homeCompOffRequests.data.slice(0, 3)"
								:key="request.name"
								:to="{ name: 'CompOffDetailView', params: { id: request.name } }"
								class="request-row"
								><div>
									<strong>{{ __("Comp Off credit") }}</strong
									><span
										>{{ formatDate(request.work_from_date) }} <span aria-hidden="true">·</span>
										{{ request.half_day ? __("0.5 day") : __("1 day") }}</span
									>
								</div>
								<span class="request-status" :class="request.status?.toLowerCase()">{{
									__(request.status)
								}}</span></router-link
							>
						</div>
						<p
							v-else-if="compOffError || homeCompOffRequests.error"
							class="request-empty request-error"
						>
							{{ __("Comp Off requests could not load. Try again from Comp Off.") }}
						</p>
						<p v-else class="request-empty">{{ __("No Comp Off credit requests yet.") }}</p>
						<router-link
							v-if="isManager"
							:to="{ name: 'CompOffListView', query: { view: 'approval' } }"
							class="manager-queue"
							><FeatherIcon name="users" class="h-4 w-4" />{{
								__("Review team Comp Off requests")
							}}</router-link
						>
					</section>
				</section>
				<section class="other-services" aria-labelledby="other-services-heading">
					<h2 id="other-services-heading">{{ __("More HR services") }}</h2>
					<div class="service-links">
						<router-link
							v-for="link in quickLinks"
							:key="link.title"
							:to="{ name: link.route }"
							:class="{ 'additional-service': !link.core, 'service-expanded': showMoreServices }"
							><component :is="link.icon" class="h-5 w-5" /><span>{{ link.title }}</span
							><FeatherIcon name="chevron-right" class="h-4 w-4"
						/></router-link>
					</div>
					<button
						class="more-services-toggle"
						:aria-expanded="showMoreServices"
						@click="showMoreServices = !showMoreServices"
					>
						{{ showMoreServices ? __("Fewer services") : __("More services")
						}}<FeatherIcon
							:name="showMoreServices ? 'chevron-up' : 'chevron-down'"
							class="h-4 w-4"
						/>
					</button>
				</section>
			</main>
		</template>
	</BaseLayout>
</template>

<script setup>
import { computed, inject, markRaw, ref } from "vue"
import { createResource, FeatherIcon } from "frappe-ui"
import { onIonViewWillEnter } from "@ionic/vue"
import BaseLayout from "@/components/BaseLayout.vue"
import CheckInPanel from "@/components/CheckInPanel.vue"
import LeaveBalance from "@/components/LeaveBalance.vue"
import AttendanceIcon from "@/components/icons/AttendanceIcon.vue"
import ShiftIcon from "@/components/icons/ShiftIcon.vue"
import ExpenseIcon from "@/components/icons/ExpenseIcon.vue"
import EmployeeAdvanceIcon from "@/components/icons/EmployeeAdvanceIcon.vue"
import SalaryIcon from "@/components/icons/SalaryIcon.vue"
import { settings } from "@/data/settings"
import { myLeaves } from "@/data/leaves"
import { bootEnablesCompOff, compOffContext } from "@/data/compOff"

const __ = inject("$translate")
const dayjs = inject("$dayjs")
const employee = inject("$employee")
const bootFlag = window.frappe?.boot?.comp_off_self_service
const compOffEnabled = computed(
	() => bootEnablesCompOff() || compOffContext.data?.enabled === true
)
const isManager = computed(() => compOffContext.data?.is_manager === true)
const employeeName = computed(() => employee?.data?.first_name || __("Employee"))
const today = computed(() => dayjs().format("dddd, D MMMM"))
const formatDate = (date) => dayjs(date).format("D MMM")
const homeCompOffRequests = createResource({ url: "hrms.api.comp_off.get_requests", auto: false })
const compOffError = ref(false)
const showMoreServices = ref(false)
const recentRequests = computed(() => {
	const leaves = (myLeaves.data || []).slice(0, 1).map((request) => ({
		key: `leave-${request.name}`,
		label: __(request.leave_type, null, "Leave Type"),
		date: request.leave_dates,
		status: request.status,
		icon: "calendar",
		route: { name: "LeaveApplicationDetailView", params: { id: request.name } },
	}))
	const credits = compOffEnabled.value
		? (homeCompOffRequests.data || []).slice(0, 1).map((request) => ({
				key: `credit-${request.name}`,
				label: __("Comp Off credit"),
				date: `${formatDate(request.work_from_date)} · ${
					request.half_day ? __("0.5 day") : __("1 day")
				}`,
				status: request.status,
				icon: "clock",
				route: { name: "CompOffDetailView", params: { id: request.name } },
		  }))
		: []
	return [...credits, ...leaves]
})
const quickLinks = [
	{
		icon: markRaw(AttendanceIcon),
		title: __("Attendance"),
		core: true,
		route: "AttendanceDashboard",
	},
	{ icon: markRaw(ShiftIcon), title: __("Request a Shift"), route: "ShiftRequestFormView" },
	{
		icon: markRaw(AttendanceIcon),
		title: __("Attendance requests"),
		route: "AttendanceRequestListView",
	},
	{
		icon: markRaw(ExpenseIcon),
		title: __("Expenses"),
		core: true,
		route: "ExpenseClaimsDashboard",
	},
	{
		icon: markRaw(EmployeeAdvanceIcon),
		title: __("Request an Advance"),
		route: "EmployeeAdvanceFormView",
	},
	{
		icon: markRaw(SalaryIcon),
		title: __("Salary slips"),
		core: true,
		route: "SalarySlipsDashboard",
	},
]

async function loadCompOff() {
	compOffError.value = false
	try {
		if (bootFlag !== false && bootFlag !== 0) await compOffContext.reload()
		if (compOffEnabled.value) await homeCompOffRequests.fetch({ team: 0 })
	} catch (_) {
		compOffError.value = true
	}
}

onIonViewWillEnter(loadCompOff)
</script>
