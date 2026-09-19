<template>
	<section class="flex flex-col w-full" aria-labelledby="leave-balance-heading">
		<div class="flex flex-row justify-between items-center px-1">
			<h2 id="leave-balance-heading" class="text-lg text-gray-800 font-bold">
				{{ __("Leave Balance") }}
			</h2>
			<router-link
				v-if="leaveBalance.data"
				:to="{ name: 'LeaveApplicationListView' }"
				class="text-sm text-gray-800 font-semibold underline underline-offset-2 focus:outline-none focus:ring-2 focus:ring-gray-700 focus:ring-offset-2 rounded"
			>
				{{ __("View Leave History") }}
			</router-link>
		</div>

		<div
			v-if="leaveBalance.loading"
			class="grid grid-cols-2 sm:grid-cols-4 gap-px mt-3 border border-gray-200 rounded-xl overflow-hidden bg-white"
			aria-label="Loading leave balances"
		>
			<div v-for="item in 3" :key="item" class="bg-white p-4 space-y-3">
				<div class="h-3 w-2/3 bg-gray-200 rounded animate-pulse"></div>
				<div class="h-6 w-1/3 bg-gray-200 rounded animate-pulse"></div>
			</div>
		</div>

		<div
			v-else-if="leaveBalance.error"
			class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mt-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
			role="alert"
		>
			<span>{{ __("We could not load your leave balances. Try again.") }}</span>
			<Button variant="subtle" class="self-start sm:self-auto" @click="leaveBalance.reload()">
				{{ __("Try again") }}
			</Button>
		</div>

		<div
			v-else-if="balanceEntries.length"
			class="grid grid-cols-2 sm:grid-cols-4 gap-px mt-3 border border-gray-200 rounded-xl overflow-hidden bg-white"
		>
			<div
				v-for="[leaveType, allocation] in balanceEntries"
				:key="leaveType"
				class="min-w-0 bg-white p-4"
			>
				<p
					class="m-0 text-sm font-medium text-gray-700"
					:title="__(leaveType, null, 'Leave Type')"
				>
					{{ __(leaveType, null, "Leave Type") }}
				</p>
				<p class="mt-2 mb-0 text-xl font-bold tabular-nums text-gray-900">
					{{ allocation.balance_leaves }}
					<span class="text-sm font-medium text-gray-600">{{ __("available") }}</span>
				</p>
				<p class="mt-1 mb-0 text-xs text-gray-600 tabular-nums">
					{{ __("{0} allocated", [allocation.allocated_leaves]) }}
				</p>
			</div>
		</div>

		<div
			v-else
			class="mt-3 rounded-xl border border-dashed border-gray-300 p-5 text-center text-sm text-gray-600"
		>
			{{ __("You have no leaves allocated") }}
		</div>
	</section>
</template>

<script setup>
import { computed, inject } from "vue"
import { leaveBalance } from "@/data/leaves"

const __ = inject("$translate")
const balanceEntries = computed(() => Object.entries(leaveBalance.data || {}))
</script>
