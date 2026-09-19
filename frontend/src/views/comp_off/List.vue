<template>
	<BaseLayout :pageTitle="__('Comp Off')">
		<template #body>
			<main class="comp-off-page" aria-live="polite">
				<router-link
					:to="{ name: 'Home' }"
					class="inline-flex items-center gap-2 mb-5 text-sm font-medium text-gray-700"
				>
					<FeatherIcon name="arrow-left" class="h-4 w-4" />{{ __("Back to home") }}
				</router-link>
				<div v-if="loadingContext" class="comp-off-skeleton" aria-label="Loading Comp Off">
					<div class="skeleton-line w-2/5"></div>
					<div class="skeleton-line"></div>
					<div class="skeleton-line w-4/5"></div>
				</div>
				<section v-else-if="contextError || !enabled" class="comp-off-empty">
					<FeatherIcon name="shield" class="h-7 w-7 text-gray-500" />
					<h1>
						{{ contextError ? __("Comp Off could not load") : __("Comp Off is unavailable") }}
					</h1>
					<p>
						{{
							contextError ||
							__("Ask HR if you believe this self-service option should be available to you.")
						}}
					</p>
					<Button variant="subtle" @click="router.push({ name: 'Home' })">{{
						__("Back to home")
					}}</Button>
				</section>
				<template v-else>
					<section class="comp-off-intro">
						<div>
							<h1>{{ __("Comp Off credit") }}</h1>
							<p>
								{{
									__(
										"Request a credit for eligible holiday work. Once approved, use Compensatory Off when applying for leave."
									)
								}}
							</p>
						</div>
						<router-link :to="{ name: 'CompOffCreateView' }" v-slot="{ navigate }">
							<Button variant="solid" class="min-h-11 shrink-0" @click="navigate"
								><template #prefix><FeatherIcon name="plus" class="h-4 w-4" /></template
								>{{ __("Request credit") }}</Button
							>
						</router-link>
					</section>

					<div v-if="error" class="comp-off-error" role="alert">
						<span>{{ error }}</span
						><Button variant="subtle" :disabled="requests.loading" @click="loadRequests">{{
							__("Try again")
						}}</Button>
					</div>

					<div
						v-if="isManager"
						class="comp-off-tabs"
						role="tablist"
						aria-label="Comp Off requests"
					>
						<button
							:disabled="requests.loading"
							:class="{ active: activeTab === 'mine' }"
							role="tab"
							:aria-selected="activeTab === 'mine'"
							@click="switchTab('mine')"
						>
							{{ __("My requests") }}
						</button>
						<button
							:disabled="requests.loading"
							:class="{ active: activeTab === 'team' }"
							role="tab"
							:aria-selected="activeTab === 'team'"
							@click="switchTab('team')"
						>
							{{ __("For approval") }}
						</button>
					</div>

					<section v-if="requests.loading" class="comp-off-list" aria-label="Loading requests">
						<div v-for="item in 3" :key="item" class="comp-off-row">
							<div class="skeleton-line w-1/3"></div>
							<div class="skeleton-line w-2/3"></div>
						</div>
					</section>
					<section
						v-else-if="requests.data?.length"
						class="comp-off-list"
						:aria-label="
							activeTab === 'team' ? __('Requests for approval') : __('My Comp Off requests')
						"
					>
						<router-link
							v-for="request in requests.data"
							:key="request.name"
							:to="{ name: 'CompOffDetailView', params: { id: request.name } }"
							class="comp-off-row"
						>
							<div class="min-w-0">
								<h2>
									{{
										activeTab === "team"
											? `${request.employee_name} · ${formatDate(request.work_from_date)}`
											: formatDate(request.work_from_date)
									}}
								</h2>
								<p>{{ creditLabel(request) }} · {{ request.reason }}</p>
							</div>
							<div class="flex items-center gap-2 shrink-0">
								<span class="comp-off-status" :class="request.status.toLowerCase()">{{
									__(request.status)
								}}</span
								><FeatherIcon name="chevron-right" class="h-5 w-5 text-gray-500" />
							</div>
						</router-link>
					</section>
					<section v-else class="comp-off-empty compact">
						<FeatherIcon name="calendar" class="h-6 w-6 text-gray-500" />
						<h2>
							{{
								activeTab === "team"
									? __("No requests waiting for you")
									: __("No Comp Off requests yet")
							}}
						</h2>
						<p>
							{{
								activeTab === "team"
									? __("Direct-report requests that need your decision will appear here.")
									: __("After working an eligible holiday, request your credit here.")
							}}
						</p>
					</section>
				</template>
			</main>
		</template>
	</BaseLayout>
</template>

<script setup>
import { computed, inject, ref } from "vue"
import { onIonViewWillEnter } from "@ionic/vue"
import { Button, FeatherIcon } from "frappe-ui"
import { useRouter } from "vue-router"
import BaseLayout from "@/components/BaseLayout.vue"
import { bootEnablesCompOff, compOffContext, compOffRequests } from "@/data/compOff"

const __ = inject("$translate")
const dayjs = inject("$dayjs")
const router = useRouter()
const activeTab = ref("mine")
const loadingContext = ref(true)
const error = ref("")
const contextError = ref("")
const enabled = computed(() => bootEnablesCompOff() || compOffContext.data?.enabled === true)
const isManager = computed(() => compOffContext.data?.is_manager === true)
const requests = compOffRequests

const formatDate = (date) => dayjs(date).format("D MMM YYYY")
const creditLabel = (request) => (request.half_day ? __("0.5 day credit") : __("1 day credit"))
const messageFor = (error) =>
	error?.messages?.[0] || error?.message || __("We could not load Comp Off requests. Try again.")

async function loadRequests() {
	if (!enabled.value) return
	error.value = ""
	try {
		await requests.fetch({ team: activeTab.value === "team" ? 1 : 0 })
	} catch (err) {
		error.value = messageFor(err)
	}
}

async function switchTab(tab) {
	activeTab.value = tab
	await loadRequests()
}

async function initialize() {
	if (window.frappe?.boot?.comp_off_self_service !== undefined && !bootEnablesCompOff()) {
		loadingContext.value = false
		return
	}
	loadingContext.value = true
	contextError.value = ""
	try {
		await compOffContext.reload()
	} catch (err) {
		contextError.value = messageFor(err)
	}
	loadingContext.value = false
	if (enabled.value && !contextError.value) await loadRequests()
}

onIonViewWillEnter(initialize)
</script>
