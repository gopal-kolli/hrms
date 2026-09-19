const routes = [
	{
		name: "CompOffListView",
		path: "/comp-off",
		component: () => import("@/views/comp_off/List.vue"),
	},
	{
		name: "CompOffCreateView",
		path: "/comp-off/new",
		component: () => import("@/views/comp_off/Form.vue"),
	},
	{
		name: "CompOffDetailView",
		path: "/comp-off/:id",
		props: true,
		component: () => import("@/views/comp_off/Detail.vue"),
	},
]

export default routes
