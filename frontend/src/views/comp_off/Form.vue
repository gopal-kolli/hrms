<template>
	<BaseLayout :pageTitle="__('Request Comp Off credit')">
		<template #body>
			<main class="comp-off-page" aria-live="polite">
				<section
					v-if="loading"
					class="comp-off-skeleton"
					aria-label="Loading Comp Off eligibility"
				>
					<div class="skeleton-line w-2/5"></div>
					<div class="skeleton-line"></div>
					<div class="skeleton-line w-3/5"></div>
				</section>
				<section v-else-if="contextError || !enabled" class="comp-off-empty">
					<h1>
						{{ contextError ? __("Comp Off could not load") : __("Comp Off is unavailable") }}
					</h1>
					<p>{{ contextError || __("This feature is not available for your account.") }}</p>
					<Button variant="subtle" @click="router.push({ name: 'Home' })">{{
						__("Back to home")
					}}</Button>
				</section>
				<form v-else class="comp-off-form" @submit.prevent="submit">
					<button
						class="comp-off-back"
						type="button"
						@click="router.push({ name: 'CompOffListView' })"
					>
						<FeatherIcon name="arrow-left" class="h-4 w-4" />{{ __("Back to Comp Off") }}
					</button>
					<div class="comp-off-copy">
						<h1>{{ __("Request a Comp Off credit") }}</h1>
						<p>
							{{
								__(
									"This asks for credit for work already completed. It does not apply for leave. Use the Leave application after a credit is approved."
								)
							}}
						</p>
					</div>
					<p v-if="manager" class="comp-off-manager">
						{{ __("Sent to {0} for approval", [manager.employee_name]) }}
					</p>
					<div v-if="!manager" class="comp-off-error" role="alert">
						{{
							__(
								"A reporting manager with an active Atlas login is needed before you can request Comp Off credit. Please contact HR."
							)
						}}
					</div>
					<div v-if="!eligibleDates.length" class="comp-off-empty compact">
						<FeatherIcon name="calendar" class="h-6 w-6 text-gray-500" />
						<h2>{{ __("No eligible work dates yet") }}</h2>
						<p>
							{{
								__(
									"There are no unclaimed holidays in your assigned calendar up to today. Contact HR if a holiday is missing."
								)
							}}
						</p>
						<router-link :to="{ name: 'CompOffListView' }">{{
							__("View my requests")
						}}</router-link>
					</div>
					<template v-else-if="manager">
						<div class="comp-off-field">
							<label for="work-date">{{ __("Eligible work date") }}</label>
							<select id="work-date" v-model="workDate" required>
								<option value="" disabled>{{ __("Select a date") }}</option>
								<option v-for="date in eligibleDates" :key="date.date" :value="date.date">
									{{ formatDate(date.date) }}
								</option>
							</select>
						</div>
						<div class="comp-off-field">
							<label for="work-duration">{{ __("Time worked") }}</label>
							<select id="work-duration" v-model="halfDay" required>
								<option :value="0">{{ __("Full day — 1 day credit") }}</option>
								<option :value="1">{{ __("Half day — 0.5 day credit") }}</option>
							</select>
							<p>{{ __("Your manager will verify the work completed and the time claimed.") }}</p>
						</div>
						<div class="comp-off-credit-preview" v-if="selectedDate">
							<FeatherIcon name="award" class="h-5 w-5" /><span>{{
								halfDay
									? __("This request becomes a 0.5 day credit after manager approval.")
									: __("This request becomes a 1 day credit after manager approval.")
							}}</span>
						</div>
						<div class="comp-off-field">
							<label for="reason">{{ __("Reason for working") }}</label>
							<textarea
								id="reason"
								v-model.trim="reason"
								rows="4"
								maxlength="500"
								required
								:placeholder="__('Briefly explain the work completed')"
							></textarea>
							<p>
								{{ __("Include enough detail for your reporting manager to review the request.") }}
							</p>
						</div>
						<div v-if="error" class="comp-off-error" role="alert">{{ error }}</div>
						<div class="comp-off-actions">
							<Button
								variant="subtle"
								type="button"
								:disabled="submitting"
								@click="router.back()"
								>{{ __("Cancel") }}</Button
							>
							<Button
								variant="solid"
								class="portal-primary-button"
								type="submit"
								:loading="submitting"
								:disabled="!canSubmit"
								>{{ __("Request credit") }}</Button
							>
						</div>
					</template>
				</form>
			</main>
		</template>
	</BaseLayout>
</template>

<script setup>
import { submitCompOff } from "@/utils/compOffRetry"
import { computed, inject, ref } from "vue"
import { onIonViewWillEnter } from "@ionic/vue"
import { Button, FeatherIcon } from "frappe-ui"
import { useRouter } from "vue-router"
import BaseLayout from "@/components/BaseLayout.vue"
import { bootEnablesCompOff, compOffContext, createCompOffRequest } from "@/data/compOff"

const __ = inject("$translate")
const dayjs = inject("$dayjs")
const router = useRouter()
const loading = ref(true)
const workDate = ref("")
const halfDay = ref(0)
const reason = ref("")
const error = ref("")
const contextError = ref("")
const submitting = ref(false)
const enabled = computed(() => bootEnablesCompOff() || compOffContext.data?.enabled === true)
const eligibleDates = computed(() => compOffContext.data?.eligible_dates || [])
const manager = computed(() => compOffContext.data?.manager || null)
const selectedDate = computed(() =>
	eligibleDates.value.find((date) => date.date === workDate.value)
)
const canSubmit = computed(() =>
	Boolean(selectedDate.value && manager.value && reason.value.trim() && !submitting.value)
)
const formatDate = (date) => dayjs(date).format("D MMMM YYYY")
const messageFor = (error) =>
	error?.messages?.[0] || error?.message || __("We could not submit this request. Try again.")

async function initialize() {
	if (window.frappe?.boot?.comp_off_self_service !== undefined && !bootEnablesCompOff()) {
		loading.value = false
		return
	}
	loading.value = true
	contextError.value = ""
	try {
		await compOffContext.reload()
	} catch (err) {
		contextError.value = messageFor(err)
	}
	loading.value = false
}

onIonViewWillEnter(initialize)

async function submit() {
	if (!canSubmit.value) return
	submitting.value = true
	error.value = ""
	try {
		const request = await submitCompOff(createCompOffRequest, {
			work_date: workDate.value,
			half_day: halfDay.value,
			reason: reason.value,
		})
		router.replace({ name: "CompOffDetailView", params: { id: request.name } })
	} catch (err) {
		error.value = messageFor(err)
	} finally {
		submitting.value = false
	}
}
</script>
