<template>
	<BaseLayout :pageTitle="__('My Details')">
		<template #body>
			<main ref="page" class="details-page">
				<router-link class="details-back" :to="{ name: 'Profile' }"
					><FeatherIcon name="arrow-left" class="h-4 w-4" />{{ __("Profile") }}</router-link
				>
				<header class="details-heading">
					<h1>{{ __("My Details") }}</h1>
					<p>{{ __("Review your recorded details and ask HR to update what has changed.") }}</p>
				</header>
				<div
					v-if="loading"
					class="details-loading"
					role="status"
					:aria-label="__('Loading your details')"
				>
					<div></div>
					<div></div>
					<div></div>
				</div>
				<div v-if="error" class="details-error" role="alert">
					<p>{{ error }}</p>
					<button type="button" @click="load">{{ __("Refresh details") }}</button>
				</div>
				<template v-if="context?.enabled">
					<p class="details-notice">
						{{ __("Your approved details remain in use for payroll until HR approves a change.") }}
					</p>
					<section v-if="active" class="details-request" aria-labelledby="active-heading">
						<div class="details-section-heading">
							<h2 id="active-heading">
								{{
									active.status === "Draft" ? __("Finish your request") : __("Your latest request")
								}}
							</h2>
							<span class="details-status" :class="statusClass(active.status)">{{
								statusLabel(active.status)
							}}</span>
						</div>
						<p v-if="active.status === 'Pending review'">
							{{ __("HR is reviewing these changes. You can track the decision here.") }}
						</p>
						<p v-else>
							{{
								__(
									"Your changes are saved, but have not been sent to HR. Add the proof below and submit, or discard this draft to start again."
								)
							}}
						</p>
						<dl class="details-proposals">
							<div v-for="change in active.changes" :key="change.key">
								<dt>{{ change.label }}</dt>
								<dd>{{ change.value }}</dd>
							</div>
						</dl>
						<template v-if="active.status === 'Draft'">
							<div v-for="kind in active.required_proofs" :key="kind" class="details-proof">
								<span v-if="active.proofs.includes(kind)"
									>{{ proofLabel(kind) }} — {{ __("saved privately") }}</span
								>
								<label v-else :for="`resume-${kind}`"
									>{{ proofLabel(kind)
									}}<input
										:id="`resume-${kind}`"
										type="file"
										accept=".pdf,.jpg,.jpeg,.png"
										:disabled="busy"
										@change="chooseFile(kind, $event)"
								/></label>
							</div>
							<p>
								{{
									__(
										"PDF, JPG or PNG · up to 5 MB per file. Visible only to you and authorised HR reviewers."
									)
								}}
							</p>
							<label class="details-consent"
								><input v-model="consent" type="checkbox" :disabled="busy" />{{
									__(
										"I confirm these details and documents are accurate and may be stored for HR review."
									)
								}}</label
							>
							<div class="details-actions">
								<button
									class="details-primary"
									type="button"
									:disabled="busy || !consent"
									@click="finishDraft"
								>
									{{ busy ? __("Submitting…") : __("Submit for HR review") }}</button
								><button type="button" :disabled="busy" @click="discard">
									{{ __("Discard draft") }}
								</button>
							</div>
						</template>
					</section>
					<form @submit.prevent="submit" :aria-busy="busy">
						<div class="details-section-heading">
							<h2>{{ __("Currently approved") }}</h2>
							<span>{{ context.employee_name }}</span>
						</div>
						<p v-if="!active" class="details-hint">
							{{
								__(
									"Select Change beside a field to enter a new value. Leave everything else as it is."
								)
							}}
						</p>
						<section
							v-for="group in groups"
							:key="group"
							class="details-group"
							:aria-label="group"
						>
							<h3>{{ group }}</h3>
							<div
								v-for="field in context.fields.filter((f) => f.group === group)"
								:key="field.key"
								class="details-row"
							>
								<div class="details-current">
									<span class="details-label">{{ field.label }}</span>
									<div>
										<span class="details-value">{{
											reveals[field.key] || field.value || __("Not recorded")
										}}</span
										><button
											v-if="field.sensitive && field.value"
											class="details-reveal"
											type="button"
											:aria-label="`${reveals[field.key] ? __('Hide') : __('Show')} ${
												field.label
											}`"
											@click="toggleReveal(field.key)"
										>
											{{ reveals[field.key] ? __("Hide") : __("Show") }}
										</button>
									</div>
									<small v-if="field.aliases_differ">{{
										__(
											"HR has different values on file. A reviewed change will bring them together."
										)
									}}</small>
								</div>
								<label v-if="!active" class="details-change"
									><input
										v-model="chosen[field.key]"
										type="checkbox"
										:disabled="busy"
										@change="selectField(field)"
									/>{{ __("Change") }}<span class="sr-only">{{ field.label }}</span></label
								>
								<div v-if="chosen[field.key] && !active" class="details-input">
									<label :for="`new-${field.key}`"
										>{{ __("New") }} {{ field.label.toLowerCase() }}</label
									><textarea
										v-if="field.type === 'textarea'"
										:id="`new-${field.key}`"
										v-model="values[field.key]"
										required
										maxlength="2000"
										:disabled="busy"
										rows="3"
									></textarea
									><select
										v-else-if="field.type === 'relation'"
										:id="`new-${field.key}`"
										v-model="values[field.key]"
										required
										:disabled="busy"
									>
										<option value="">{{ __("Choose relationship") }}</option>
										<option v-for="option in field.options" :key="option">
											{{ option }}
										</option></select
									><input
										v-else
										:id="`new-${field.key}`"
										v-model="values[field.key]"
										required
										:type="inputType(field)"
										:inputmode="inputMode(field)"
										:maxlength="maxLength(field)"
										:disabled="busy"
										autocomplete="off"
										:placeholder="placeholder(field)"
									/>
								</div>
							</div>
						</section>
						<section
							v-if="changedFields.length && !active"
							class="details-submit"
							aria-labelledby="submit-heading"
						>
							<h2 id="submit-heading">{{ __("Send your changes for review") }}</h2>
							<p>
								{{ changedFields.length }}
								{{ changedFields.length === 1 ? __("detail selected.") : __("details selected.") }}
								{{ __("HR will compare these with your approved record.") }}
							</p>
							<p v-if="retryOf">
								{{
									__(
										"This is a correction to an earlier request. The previous submission will remain in your history."
									)
								}}
							</p>
							<div v-for="kind in requiredProofs" :key="kind" class="details-proof">
								<label :for="`proof-${kind}`"
									>{{ proofLabel(kind)
									}}<input
										:id="`proof-${kind}`"
										type="file"
										accept=".pdf,.jpg,.jpeg,.png"
										required
										:disabled="busy"
										@change="chooseFile(kind, $event)"
								/></label>
							</div>
							<p v-if="requiredProofs.length">
								{{
									__(
										"PDF, JPG or PNG · up to 5 MB per file. Upload only the proof needed for your changes."
									)
								}}
							</p>
							<label class="details-consent"
								><input v-model="consent" type="checkbox" required :disabled="busy" />{{
									__(
										"I confirm these details and documents are accurate and may be stored for HR review."
									)
								}}</label
							>
							<button class="details-primary" type="submit" :disabled="busy || !consent">
								{{ busy ? __("Submitting…") : __("Submit for HR review") }}
							</button>
						</section>
					</form>
					<section class="details-history" aria-labelledby="history-heading">
						<h2 id="history-heading">{{ __("Request history") }}</h2>
						<p v-if="!history.length">
							{{ __("Your submitted changes and HR decisions will appear here.") }}
						</p>
						<details v-for="request in history" :key="request.name">
							<summary>
								<span>{{ formatDate(request.created) }}</span
								><span class="details-status" :class="statusClass(request.status)">{{
									statusLabel(request.status)
								}}</span>
							</summary>
							<p v-if="request.review_note" class="details-review-note">
								{{ request.review_note }}
							</p>
							<dl class="details-proposals">
								<div v-for="change in request.changes" :key="change.key">
									<dt>
										{{ change.label
										}}<small v-if="request.status === 'Approved'">
											—
											{{
												request.applied_fields.includes(change.key)
													? __("updated")
													: __("kept unchanged")
											}}</small
										>
									</dt>
									<dd>{{ change.value }}</dd>
								</div>
							</dl>
							<div class="details-proof-links">
								<a
									v-for="kind in request.proofs"
									:key="kind"
									:href="proofUrl(request.name, kind)"
									target="_blank"
									rel="noopener"
									>{{ proofLabel(kind) }}</a
								>
							</div>
							<button
								v-if="request.status === 'Needs correction' && !active"
								type="button"
								@click="correct(request)"
							>
								{{ __("Prepare a corrected request") }}
							</button>
						</details>
					</section>
					<p class="details-controlled">
						{{
							__(
								"Salary, joining date, department and manager are managed by HR. Contact HR if these need correction."
							)
						}}
					</p>
				</template>
				<p v-else-if="context && !loading">
					{{
						__("My Details is not available yet. Please contact HR for a personal-detail update.")
					}}
				</p>
				<p v-if="success" class="details-success" role="status">{{ success }}</p>
			</main>
		</template>
	</BaseLayout>
</template>

<script setup>
import { computed, inject, nextTick, onMounted, onBeforeUnmount, ref } from "vue"
import { createResource, FeatherIcon } from "frappe-ui"
import BaseLayout from "@/components/BaseLayout.vue"
const __ = inject("$translate", (text) => text)
const page = ref(null)
const context = ref(null),
	loading = ref(true),
	busy = ref(false),
	error = ref(""),
	success = ref("")
const chosen = ref({}),
	values = ref({}),
	reveals = ref({}),
	files = ref({}),
	consent = ref(false),
	retryOf = ref("")
let requestId = crypto.randomUUID()
const active = computed(() =>
	context.value?.requests.find((r) => ["Draft", "Pending review"].includes(r.status))
)
const history = computed(
	() =>
		context.value?.requests.filter((r) => !["Draft", "Pending review"].includes(r.status)) || []
)
const groups = computed(() => [...new Set(context.value?.fields.map((f) => f.group) || [])])
const changedFields = computed(
	() => context.value?.fields.filter((f) => chosen.value[f.key]) || []
)
const requiredProofs = computed(() => [
	...new Set(changedFields.value.map((f) => f.proof).filter(Boolean)),
])
const api = (method, params = {}) =>
	createResource({ url: `hrms.api.my_details.${method}` }).submit(params)
const message = (e) =>
	e?.messages?.[0] ||
	e?.message ||
	__("We could not save this request. Refresh to check its status, then retry.")
const statusClass = (status) =>
	({ "Pending review": "pending", Approved: "approved", "Needs correction": "correction" }[
		status
	] || "draft")
const statusLabel = (status) => (status === "Draft" ? __("Not submitted") : __(status))
const proofLabel = (kind) =>
	({
		bank: __("Bank proof (cancelled cheque or bank statement)"),
		pan: __("PAN copy"),
		aadhaar: __("Aadhaar copy"),
		statutory: __("UAN / ESI proof"),
	}[kind])
const proofUrl = (request, kind) =>
	`/api/method/hrms.api.my_details.download_proof?request=${encodeURIComponent(
		request
	)}&kind=${kind}`
const formatDate = (value) =>
	value
		? new Date(value.replace(" ", "T")).toLocaleDateString(undefined, {
				day: "numeric",
				month: "short",
				year: "numeric",
		  })
		: ""
const inputType = (field) =>
	field.type === "email"
		? "email"
		: field.type === "date"
		? "date"
		: field.sensitive
		? "password"
		: "text"
const inputMode = (field) =>
	["bank", "aadhaar", "uan", "esi", "mobile", "pin"].includes(field.type) ? "numeric" : "text"
const maxLength = (field) =>
	({ bank: 18, aadhaar: 12, uan: 12, esi: 10, mobile: 10, pin: 6, pan: 10, ifsc: 11 }[
		field.type
	] || 140)
const placeholder = (field) =>
	({
		bank: "9–18 digits",
		aadhaar: "12 digits",
		uan: "12 digits",
		esi: "10 digits",
		mobile: "10 digits",
		pin: "6 digits",
		ifsc: "ABCD0123456",
		pan: "ABCDE1234F",
	}[field.type] || "")
function selectField(field) {
	if (!chosen.value[field.key]) delete values.value[field.key]
	else values.value[field.key] = field.sensitive ? "" : field.value
	requestId = crypto.randomUUID()
}
async function load() {
	loading.value = true
	error.value = ""
	reveals.value = {}
	try {
		context.value = await api("get_context")
	} catch (e) {
		error.value = message(e)
	} finally {
		loading.value = false
	}
}
async function toggleReveal(field) {
	if (reveals.value[field]) {
		delete reveals.value[field]
		return
	}
	try {
		reveals.value[field] = (await api("reveal_field", { field })).value
	} catch (e) {
		error.value = message(e)
	}
}
function chooseFile(kind, event) {
	const file = event.target.files[0]
	if (!file) return
	if (file.size > 5 * 1024 * 1024) {
		error.value = __("Choose a file smaller than 5 MB.")
		event.target.value = ""
		delete files.value[kind]
		return
	}
	files.value[kind] = file
	error.value = ""
}
async function upload(request, kind) {
	const form = new FormData()
	form.append("request", request)
	form.append("kind", kind)
	form.append("file", files.value[kind])
	const response = await fetch("/api/method/hrms.api.my_details.upload_proof", {
		method: "POST",
		credentials: "same-origin",
		headers: { "X-Frappe-CSRF-Token": window.frappe.csrf_token },
		body: form,
	})
	if (!response.ok)
		throw new Error(
			__("Proof upload failed. Your draft is saved; refresh and retry the missing proof.")
		)
}
async function finish(request) {
	for (const kind of request.required_proofs) {
		if (request.proofs.includes(kind)) continue
		if (!files.value[kind]) throw new Error(__("Choose each required proof before submitting."))
		await upload(request.name, kind)
	}
	await api("submit_request", { request: request.name, consent: true })
	chosen.value = {}
	values.value = {}
	files.value = {}
	consent.value = false
	retryOf.value = ""
	requestId = crypto.randomUUID()
	success.value = __(
		"Your change request has been sent to HR. Your approved details are unchanged."
	)
}
async function submit() {
	if (busy.value || !consent.value) return
	busy.value = true
	error.value = ""
	success.value = ""
	try {
		const changes = Object.fromEntries(
			changedFields.value.map((f) => [f.key, values.value[f.key] || ""])
		)
		const draft = await api("begin_request", {
			changes,
			expected_version: context.value.version,
			request_id: requestId,
			retry_of: retryOf.value,
		})
		await finish(draft)
		await load()
		await nextTick()
		page.value?.scrollIntoView({ block: "start" })
	} catch (e) {
		const failure = message(e)
		await load()
		error.value = failure
	} finally {
		busy.value = false
	}
}
async function finishDraft() {
	if (busy.value || !consent.value) return
	busy.value = true
	error.value = ""
	try {
		await finish(active.value)
		await load()
		await nextTick()
		page.value?.scrollIntoView({ block: "start" })
	} catch (e) {
		const failure = message(e)
		await load()
		error.value = failure
	} finally {
		busy.value = false
	}
}
async function discard() {
	busy.value = true
	try {
		await api("discard_draft", { request: active.value.name })
		chosen.value = {}
		values.value = {}
		files.value = {}
		consent.value = false
		requestId = crypto.randomUUID()
		await load()
		await nextTick()
		page.value?.scrollIntoView({ block: "start" })
	} catch (e) {
		error.value = message(e)
	} finally {
		busy.value = false
	}
}
function correct(request) {
	retryOf.value = request.name
	chosen.value = {}
	values.value = {}
	for (const change of request.changes) {
		const field = context.value.fields.find((f) => f.key === change.key)
		chosen.value[field.key] = true
		values.value[field.key] = field.sensitive ? "" : change.value
	}
	requestId = crypto.randomUUID()
	success.value = __("Select and correct the details above, then submit a new request.")
}
function hideSensitive() {
	if (document.hidden) reveals.value = {}
}
onMounted(() => {
	load()
	document.addEventListener("visibilitychange", hideSensitive)
})
onBeforeUnmount(() => {
	reveals.value = {}
	values.value = {}
	files.value = {}
	document.removeEventListener("visibilitychange", hideSensitive)
})
</script>

<style scoped>
.details-page {
	width: 100%;
	padding: 24px 20px 80px;
	max-width: 860px;
	margin: 0 auto;
	color: #172f35;
}
.details-back {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	min-height: 44px;
	color: #006b64;
}
.details-heading {
	margin: 16px 0 24px;
}
h1 {
	font-size: 2rem;
	font-weight: 760;
	letter-spacing: -0.025em;
}
h2 {
	font-size: 1.15rem;
	font-weight: 750;
}
h3 {
	font-size: 1rem;
	font-weight: 750;
	padding: 18px 20px;
	border-bottom: 1px solid #c9deda;
}
p {
	line-height: 1.55;
	max-width: 70ch;
}
.details-heading p,
.details-hint,
.details-controlled {
	color: #547076;
	margin-top: 8px;
}
.details-notice {
	padding: 16px 0;
	margin-bottom: 24px;
	border-block: 1px solid #c9deda;
}
.details-section-heading {
	display: flex;
	justify-content: space-between;
	align-items: center;
	gap: 12px;
	flex-wrap: wrap;
	margin-bottom: 8px;
}
.details-section-heading > span:not(.details-status) {
	max-width: 100%;
	overflow-wrap: anywhere;
	color: #547076;
	font-size: 0.9rem;
}
.details-group {
	margin-top: 20px;
	background: #fff;
	border: 1px solid #c9deda;
	border-radius: 14px;
}
.details-row {
	display: grid;
	grid-template-columns: 1fr auto;
	gap: 12px 20px;
	padding: 16px 20px;
}
.details-row + .details-row {
	border-top: 1px solid #e3eeeb;
}
.details-label {
	display: block;
	color: #547076;
	font-size: 0.85rem;
	margin-bottom: 5px;
}
.details-value,
dd {
	white-space: pre-wrap;
	overflow-wrap: anywhere;
	font-variant-numeric: tabular-nums;
}
.details-change,
.details-consent {
	display: flex;
	gap: 10px;
	align-items: center;
}
.details-change {
	min-height: 44px;
	font-size: 0.9rem;
}
input[type="checkbox"] {
	width: 18px;
	height: 18px;
	flex-shrink: 0;
	accent-color: #006b64;
}
.details-input {
	grid-column: 1 / -1;
}
.details-input label,
.details-proof label {
	display: block;
	font-size: 0.9rem;
	font-weight: 650;
}
.details-input input,
textarea,
select {
	display: block;
	width: 100%;
	min-height: 46px;
	border: 1px solid #a9c7c0;
	border-radius: 10px;
	padding: 10px 12px;
	background: white;
	color: #172f35;
	margin-top: 6px;
	caret-color: #006b64;
}
input::placeholder {
	color: #547076;
	opacity: 1;
}
button,
a {
	text-underline-offset: 4px;
}
button {
	min-height: 44px;
	padding: 8px 12px;
	border-radius: 10px;
	color: #006b64;
	font-weight: 650;
}
button:hover {
	background: #eaf4f2;
}
button:disabled {
	opacity: 0.65;
	cursor: not-allowed;
}
button:focus-visible,
a:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible,
summary:focus-visible {
	outline: 3px solid #7cb5ac;
	outline-offset: 3px;
}
.details-primary {
	background: #006b64;
	color: white;
	padding: 12px 20px;
}
.details-primary:hover {
	background: #00544f;
}
.details-primary:disabled {
	background: #d3e4e1;
	color: #486660;
	opacity: 1;
}
.details-reveal {
	margin-left: 8px;
	font-size: 0.85rem;
}
.details-submit,
.details-request {
	background: white;
	padding: 24px;
	border: 1px solid #c9deda;
	border-radius: 14px;
	margin: 24px 0;
}
.details-submit p,
.details-request p {
	margin: 10px 0;
	color: #547076;
}
.details-proof {
	margin: 18px 0;
}
.details-proof input {
	display: block;
	margin-top: 8px;
	width: 100%;
	font-weight: 400;
	min-height: 44px;
}
.details-consent {
	align-items: flex-start;
	margin: 22px 0;
	line-height: 1.5;
	font-size: 0.9rem;
}
.details-consent input {
	margin-top: 3px;
}
.details-actions {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
}
.details-status {
	padding: 5px 10px;
	border-radius: 999px;
	font-size: 0.8rem;
	font-weight: 700;
	background: #eaf4f2;
}
.details-status.pending {
	color: #805b00;
	background: #fff4d2;
}
.details-status.approved {
	color: #086b4e;
	background: #ddf4eb;
}
.details-status.correction {
	color: #9b3323;
	background: #fde7e2;
}
.details-history {
	margin-top: 32px;
}
.details-history > p {
	margin-top: 12px;
	color: #547076;
}
details {
	padding: 12px 0;
	border-bottom: 1px solid #c9deda;
}
summary {
	cursor: pointer;
	min-height: 44px;
}
summary .details-status {
	float: right;
}
.details-proposals {
	margin: 16px 0;
}
.details-proposals > div {
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 16px;
	padding: 8px 0;
}
.details-proposals dt {
	color: #547076;
}
.details-proof-links {
	display: flex;
	flex-wrap: wrap;
	gap: 14px;
	margin: 12px 0;
}
.details-proof-links a {
	color: #006b64;
	min-height: 44px;
	text-decoration: underline;
}
.details-review-note {
	white-space: pre-wrap;
	margin-top: 12px;
}
.details-error {
	background: #fff4f0;
	padding: 16px;
	border-radius: 10px;
	color: #9b3323;
	margin: 16px 0;
}
.details-success {
	background: #ddf4eb;
	color: #086b4e;
	padding: 16px;
	margin: 16px 0;
	border-radius: 10px;
}
.details-controlled {
	margin: 24px 0;
	font-size: 0.9rem;
}
small {
	font-size: 0.8rem;
	line-height: 1.5;
}
.details-current small {
	display: block;
	color: #805b00;
	margin-top: 8px;
}
.details-loading {
	padding: 24px 0;
}
.details-loading div {
	height: 36px;
	background: #d3e4e1;
	border-radius: 8px;
	margin: 16px 0;
}
.details-loading div:nth-child(2) {
	width: 80%;
}
::selection {
	background: #b9ddd8;
	color: #172f35;
}
@media (max-width: 640px) {
	.details-page {
		padding: 16px 12px 32px;
	}
	h1 {
		font-size: 1.7rem;
	}
	.details-row {
		padding: 14px 16px;
		gap: 10px;
	}
	h3 {
		padding: 16px;
	}
	.details-submit,
	.details-request {
		padding: 16px;
	}
	.details-proposals > div {
		grid-template-columns: 1fr;
		gap: 4px;
	}
	.details-primary {
		width: 100%;
	}
}
</style>
