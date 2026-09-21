<template>
	<BaseLayout :pageTitle="__('Comp Off request')">
		<template #body>
			<main class="comp-off-page" aria-live="polite">
				<section v-if="loading" class="comp-off-skeleton" aria-label="Loading Comp Off request">
					<div class="skeleton-line w-1/3"></div>
					<div class="skeleton-line"></div>
					<div class="skeleton-line w-4/5"></div>
				</section>
				<section v-else-if="error || !request" class="comp-off-empty">
					<FeatherIcon name="alert-circle" class="h-7 w-7 text-gray-500" />
					<h1>{{ __("Request unavailable") }}</h1>
					<p>{{ error || __("This request could not be found.") }}</p>
					<Button variant="subtle" @click="router.push({ name: 'CompOffListView' })">{{
						__("Back to Comp Off")
					}}</Button>
				</section>
				<template v-else>
					<button
						class="comp-off-back"
						type="button"
						@click="router.push({ name: 'CompOffListView' })"
					>
						<FeatherIcon name="arrow-left" class="h-4 w-4" />{{ __("Back to Comp Off") }}
					</button>
					<section class="comp-off-detail-heading">
						<div>
							<h1>
								{{
									request.employee_name
										? `${request.employee_name} · ${formatDate(request.work_from_date)}`
										: formatDate(request.work_from_date)
								}}
							</h1>
							<p>
								{{
									request.half_day ? __("0.5 day Comp Off credit") : __("1 day Comp Off credit")
								}}
							</p>
						</div>
						<span class="comp-off-status" :class="request.status.toLowerCase()">{{
							__(request.status)
						}}</span>
					</section>
					<section class="comp-off-detail-card">
						<div>
							<span>{{ __("Reason for working") }}</span>
							<p>{{ request.reason }}</p>
						</div>
						<div>
							<span>{{ __("Requested") }}</span>
							<p>{{ formatDateTime(request.creation) }}</p>
						</div>
						<div v-if="request.decision_by">
							<span>{{ __("Decision") }}</span>
							<p>{{ request.decision_reason || __("No additional note") }}</p>
							<small>{{
								__("by {0} on {1}", [request.decision_by, formatDateTime(request.decision_on)])
							}}</small>
						</div>
					</section>
					<p v-if="request.status === 'Approved'" class="comp-off-approved-note">
						<FeatherIcon name="check-circle" class="h-5 w-5" />{{
							__(
								"Your credit is approved. Apply for leave with the Compensatory Off leave type when you are ready to use it."
							)
						}}
					</p>
					<section
						v-if="request.can_approve && request.status === 'Pending'"
						class="comp-off-decision"
					>
						<h2>{{ __("Manager decision") }}</h2>
						<p>
							{{
								__(
									"Verify the work completed and time claimed, then decide the {0} credit for {1}.",
									[request.half_day ? "0.5 day" : "1 day", request.employee_name]
								)
							}}
						</p>
						<label for="decision-reason"
							>{{ __("Note for the employee") }}
							<span>{{ __("(required when rejecting)") }}</span></label
						>
						<textarea
							id="decision-reason"
							v-model.trim="decisionReason"
							rows="3"
							maxlength="500"
							:placeholder="__('Add a note if needed')"
						></textarea>
						<div v-if="decisionError" class="comp-off-error" role="alert">{{ decisionError }}</div>
						<div class="comp-off-actions">
							<Button
								variant="subtle"
								:loading="deciding === 'Rejected'"
								:disabled="Boolean(deciding)"
								@click="decide('Rejected')"
								>{{ __("Reject") }}</Button
							><Button
								variant="solid"
								class="portal-primary-button"
								:loading="deciding === 'Approved'"
								:disabled="Boolean(deciding)"
								@click="decide('Approved')"
								>{{ __("Approve {0} credit", [request.half_day ? "0.5 day" : "1 day"]) }}</Button
							>
						</div>
					</section>
				</template>
			</main>
		</template>
	</BaseLayout>
</template>

<script setup>
import { submitCompOff } from "@/utils/compOffRetry"
import { inject, ref } from "vue"
import { onIonViewWillEnter } from "@ionic/vue"
import { Button, FeatherIcon } from "frappe-ui"
import { useRouter } from "vue-router"
import BaseLayout from "@/components/BaseLayout.vue"
import {
	bootEnablesCompOff,
	compOffContext,
	compOffRequests,
	decideCompOffRequest,
} from "@/data/compOff"

const props = defineProps({ id: { type: String, required: true } })
const __ = inject("$translate")
const dayjs = inject("$dayjs")
const router = useRouter()
const loading = ref(true)
const error = ref("")
const request = ref(null)
const decisionReason = ref("")
const decisionError = ref("")
const deciding = ref("")
const formatDate = (date) => dayjs(date).format("D MMMM YYYY")
const formatDateTime = (date) => (date ? dayjs(date).format("D MMM YYYY, h:mm A") : "")
const messageFor = (error) =>
	error?.messages?.[0] || error?.message || __("We could not complete that decision. Try again.")

async function load() {
	loading.value = true
	error.value = ""
	request.value = null
	try {
		if (window.frappe?.boot?.comp_off_self_service !== undefined && !bootEnablesCompOff()) return
		await compOffContext.reload()
		if (!(bootEnablesCompOff() || compOffContext.data?.enabled)) return
		const own = await compOffRequests.fetch({ team: 0 })
		request.value = own.find((item) => item.name === props.id)
		if (!request.value && compOffContext.data?.is_manager) {
			const team = await compOffRequests.fetch({ team: 1 })
			request.value = team.find((item) => item.name === props.id)
		}
	} catch (err) {
		error.value = messageFor(err)
	} finally {
		loading.value = false
	}
}

async function decide(decision) {
	if (decision === "Rejected" && !decisionReason.value.trim()) {
		decisionError.value = __("Add a reason before rejecting this request.")
		return
	}
	deciding.value = decision
	decisionError.value = ""
	try {
		request.value = await submitCompOff(decideCompOffRequest, {
			name: request.value.name,
			decision,
			reason: decisionReason.value,
		})
	} catch (err) {
		decisionError.value = messageFor(err)
	} finally {
		deciding.value = ""
	}
}

onIonViewWillEnter(load)
</script>
