<template>
	<section class="leave-balances" aria-labelledby="leave-balance-heading">
		<div class="leave-balances-head">
			<h2 id="leave-balance-heading">
				{{ __("Available balances") }}
			</h2>
			<router-link
				v-if="leaveBalance.data"
				:to="{ name: 'LeaveApplicationListView' }"
				class="portal-text-link"
			>
				{{ __("History") }}
			</router-link>
		</div>

		<div
			v-if="leaveBalance.loading"
			class="leave-balance-grid is-loading"
			aria-label="Loading leave balances"
		>
			<div v-for="item in 4" :key="item" class="leave-balance-cell">
				<div class="balance-skeleton balance-skeleton-label"></div>
				<div class="balance-skeleton balance-skeleton-value"></div>
			</div>
		</div>

		<div v-else-if="leaveBalance.error" class="portal-alert" role="alert">
			<span>{{ __("We could not load your leave balances. Try again.") }}</span>
			<Button variant="subtle" class="self-start sm:self-auto" @click="leaveBalance.reload()">
				{{ __("Try again") }}
			</Button>
		</div>

		<div v-else-if="balanceEntries.length" class="leave-balance-grid">
			<div
				v-for="[leaveType, allocation] in balanceEntries"
				:key="leaveType"
				class="leave-balance-cell"
			>
				<FeatherIcon :name="balanceIcon(leaveType)" class="balance-icon" aria-hidden="true" />
				<p class="leave-balance-name" :title="__(leaveType, null, 'Leave Type')">
					{{ __(leaveType, null, "Leave Type") }}
				</p>
				<p class="leave-balance-value">
					{{ allocation.balance_leaves }}
					<span>{{ Number(allocation.balance_leaves) === 1 ? __("day") : __("days") }}</span>
				</p>
				<p class="leave-balance-allocation">
					{{ __("{0} allocated", [allocation.allocated_leaves]) }}
				</p>
			</div>
		</div>

		<div v-else class="leave-balance-empty">
			{{ __("You have no leaves allocated") }}
		</div>
	</section>
</template>

<script setup>
import { FeatherIcon } from "frappe-ui"
import { computed, inject } from "vue"
import { leaveBalance } from "@/data/leaves"

const __ = inject("$translate")
const balanceIcon = (type) =>
	/sick/i.test(type) ? "heart" : /compensatory|comp off/i.test(type) ? "clock" : "calendar"
const balanceEntries = computed(() => Object.entries(leaveBalance.data || {}))
</script>
