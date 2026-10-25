<template>
	<ion-page>
		<ion-content class="ion-padding">
			<div class="flex flex-col h-screen w-screen">
				<div class="w-full sm:w-96">
					<header
						class="flex flex-row bg-white shadow-sm py-4 px-3 items-center justify-between border-b sticky top-0 z-10"
					>
						<div class="flex flex-row items-center">
							<Button variant="ghost" class="!pl-0 hover:bg-white" @click="router.back()">
								<FeatherIcon name="chevron-left" class="h-5 w-5" />
							</Button>
							<h2 class="text-xl font-semibold text-gray-900">{{ __("Profile") }}</h2>
						</div>
					</header>

					<div class="flex flex-col items-center mt-5 p-4">
						<!-- Profile Image -->
						<img
							v-if="user.data.user_image"
							class="h-24 w-24 rounded-full object-cover"
							:src="user.data.user_image"
							:alt="user.data.first_name"
						/>
						<div
							v-else
							class="flex items-center justify-center bg-gray-200 uppercase text-gray-600 h-24 w-24 rounded-full object-cover"
						>
							{{ user.data.first_name[0] }}
						</div>

						<div class="flex flex-col gap-1.5 items-center mt-2 mb-5">
							<span v-if="employee" class="text-lg font-bold text-gray-900">{{
								employee?.data?.employee_name
							}}</span>
							<span v-if="employee" class="font-normal text-sm text-gray-500">{{
								employee?.data?.designation
							}}</span>
						</div>

						<router-link
							v-if="profile.data?.my_details_enabled"
							:to="{ name: 'MyDetails' }"
							class="my-details-entry"
							>{{ __("My Details")
							}}<span>{{ __("Bank, identity, contact and nominee details") }}</span></router-link
						>
						<!-- Profile Links -->
						<div class="flex flex-col gap-5 my-4 w-full">
							<div class="flex flex-col bg-white rounded">
								<div
									class="flex flex-row cursor-pointer flex-start p-4 items-center justify-between border-b"
									v-for="link in profileLinks"
									:key="link.title"
									@click="openInfoModal(link)"
								>
									<div class="flex flex-row items-center gap-3 grow">
										<FeatherIcon :name="link.icon" class="h-5 w-5 text-gray-500" />
										<div class="text-base font-normal text-gray-800">
											{{ link.title }}
										</div>
									</div>
									<FeatherIcon name="chevron-right" class="h-5 w-5 text-gray-500" />
								</div>
							</div>
						</div>

						<!-- Settings -->
						<div class="flex flex-col gap-5 my-4 w-full">
							<div class="flex flex-col bg-white rounded">
								<router-link
									:to="{ name: 'Settings' }"
									class="flex flex-row cursor-pointer flex-start p-4 items-center justify-between border-b"
								>
									<div class="flex flex-row items-center gap-3 grow">
										<FeatherIcon name="settings" class="h-5 w-5 text-gray-500" />
										<div class="text-base font-normal text-gray-800">
											{{ __("Settings") }}
										</div>
									</div>
									<FeatherIcon name="chevron-right" class="h-5 w-5 text-gray-500" />
								</router-link>
							</div>
						</div>

						<Button @click="logout" variant="outline" theme="red" class="w-full shadow py-4 mt-5">
							<template #prefix>
								<FeatherIcon name="log-out" class="w-4" />
							</template>
							{{ __("Log Out") }}
						</Button>
					</div>
				</div>
			</div>

			<ion-modal
				ref="modal"
				:is-open="isInfoModalOpen"
				@didDismiss="closeInfoModal"
				:initial-breakpoint="1"
				:breakpoints="[0, 1]"
			>
				<ProfileInfoModal
					v-if="selectedItem"
					:title="selectedItem.title"
					:data="
						selectedItem.fields.map((field) => {
							const [label, fieldtype] = getFieldInfo(field)
							return {
								fieldname: field,
								value: getFieldValue(field),
								label: label,
								fieldtype: fieldtype,
							}
						})
					"
				/>
			</ion-modal>
		</ion-content>
	</ion-page>
</template>

<script setup>
import { computed, inject, ref, watch, onMounted, onBeforeUnmount } from "vue"
import { useRouter } from "vue-router"
import { IonPage, IonContent } from "@ionic/vue"
import { FeatherIcon, createDocumentResource, createResource, toast } from "frappe-ui"

import { showErrorAlert } from "@/utils/dialogs"
import { formatCurrency } from "@/utils/formatters"

import ProfileInfoModal from "@/components/ProfileInfoModal.vue"

import { arePushNotificationsEnabled } from "@/data/notifications"

const DOCTYPE = "Employee"

const socket = inject("$socket")
const session = inject("$session")
const user = inject("$user")
const employee = inject("$employee")
const __ = inject("$translate")

const router = useRouter()

const profileLinks = [
	{
		icon: "user",
		title: __("Employee Details"),
		fields: [
			"employee_name",
			"employee_number",
			"gender",
			"date_of_birth",
			"date_of_joining",
			"blood_group",
		],
	},
	{
		icon: "file",
		title: __("Company Information"),
		fields: [
			"company",
			"department",
			"designation",
			"branch",
			"grade",
			"reports_to",
			"employment_type",
		],
	},
	{
		icon: "book",
		title: __("Contact Information"),
		fields: ["cell_number", "personal_email", "company_email", "prefered_contact_email"],
	},
	{
		icon: "dollar-sign",
		title: __("Salary Information"),
		fields: ["ctc", "payroll_cost_center", "salary_mode"],
	},
]

const isInfoModalOpen = ref(false)
const selectedItem = ref(null)

const allowPushNotifications = computed(
	() => window.frappe?.boot.push_relay_server_url && arePushNotificationsEnabled.data
)

const openInfoModal = async (request) => {
	selectedItem.value = request
	isInfoModalOpen.value = true
}

const closeInfoModal = async (_request) => {
	isInfoModalOpen.value = false
	selectedItem.value = null
}

const profile = createResource({ url: "hrms.api.my_details.get_profile", auto: true })

const getFieldInfo = (fieldname) => {
	const field = (profile.data?.fields || []).find((field) => field.fieldname === fieldname)
	return [__(field?.label, null, "Employee"), field?.fieldtype]
}

const getFieldValue = (fieldname) => {
	if (fieldname === "ctc")
		return formatCurrency(profile.data?.values?.ctc, profile.data?.values?.salary_currency)
	if (fieldname === "employee_number" && !profile.data?.values?.[fieldname]) {
		return employee.data?.name
	}
	if (fieldname === "reports_to") {
		return profile.data?.values?.[fieldname]
	}
	return profile.data?.values?.[fieldname]
}

const logout = async () => {
	try {
		await session.logout.submit()
	} catch (e) {
		const msg = __("An error occurred while attempting to log out!")
		console.error(msg, e)
		showErrorAlert(msg)
	}
}

onMounted(() => {
	socket.emit("doctype_subscribe", DOCTYPE)
	socket.on("list_update", (data) => {
		if (data.doctype === DOCTYPE && data.name === employee.data.name) {
			profile.reload()
		}
	})
})

onBeforeUnmount(() => {
	socket.emit("doctype_unsubscribe", DOCTYPE)
	socket.off("list_update")
})
</script>

<style scoped>
.my-details-entry {
	display: block;
	width: 100%;
	padding: 16px;
	color: #006b64;
	border: 1px solid #c9deda;
	border-radius: 10px;
	font-weight: 700;
}
.my-details-entry span {
	display: block;
	margin-top: 6px;
	font-size: 0.85rem;
	font-weight: 400;
	color: #547076;
}
.my-details-entry:focus-visible {
	outline: 3px solid #7cb5ac;
	outline-offset: 3px;
}
</style>
