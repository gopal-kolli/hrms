<template>
	<ion-page>
		<ion-header class="ion-no-border portal-header">
			<div class="portal-header-inner">
				<div class="portal-brandbar">
					<div class="flex flex-row justify-between items-center w-full">
						<div class="portal-brand" aria-label="SOLARA Atlas">
							<span>SOLARA</span><small>Atlas</small>
						</div>
						<div class="flex flex-row items-center gap-3 ml-auto">
							<router-link
								:to="{ name: 'Notifications' }"
								v-slot="{ navigate }"
								class="portal-icon-link"
								:aria-label="__('Notifications')"
							>
								<span class="relative inline-block" @click="navigate">
									<FeatherIcon name="bell" class="h-6 w-6" />
									<span
										v-if="unreadNotificationsCount.data"
										class="absolute top-0 right-0.5 inline-block w-2 h-2 bg-red-600 rounded-full border border-white"
									>
									</span>
								</span>
							</router-link>
							<router-link
								:to="{ name: 'Profile' }"
								class="portal-avatar-link"
								:aria-label="__('Open profile')"
							>
								<Avatar :image="user.data.user_image" :label="user.data.first_name" size="xl" />
							</router-link>
						</div>
					</div>
				</div>
			</div>
		</ion-header>

		<ion-content class="ion-no-padding portal-ion-content">
			<div class="portal-content">
				<slot name="body"></slot>
			</div>
		</ion-content>
	</ion-page>
</template>

<script setup>
import { IonHeader, IonContent, IonPage } from "@ionic/vue"
import { FeatherIcon, Avatar } from "frappe-ui"

import { unreadNotificationsCount } from "@/data/notifications"

import { inject } from "vue"

const user = inject("$user")

const props = defineProps({
	pageTitle: {
		type: String,
		required: false,
		default: "",
	},
})
</script>
