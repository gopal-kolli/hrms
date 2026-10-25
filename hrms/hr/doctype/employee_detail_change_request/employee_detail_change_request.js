// Immutable history, reviewed through the guarded service; no generic form save.
frappe.ui.form.on("Employee Detail Change Request", {
	refresh(frm) {
		frm.disable_save();
		if (frm.doc.status !== "Pending review") return;
		frm.add_custom_button(__("Review changes"), async () => {
			const { message: review } = await frappe.call({
				method: "hrms.api.my_details.review_request",
				args: { request: frm.doc.name },
			});
			const esc = frappe.utils.escape_html;
			const blocked = review.stale || review.blockers.length;
			const rows = review.rows.map((row, i) => ({
				fieldname: `approve_${i}`,
				fieldtype: "Check",
				label: row.label,
				default: 0,
				description: `${__("Current")}: ${row.current
					.map((v) => esc(v.value || __("Not recorded")))
					.join(" / ")}<br>${__("Proposed")}: ${esc(row.proposed)}`,
			}));
			const proofLinks = review.proofs
				.map(
					(kind) =>
						`<a target="_blank" rel="noopener" href="/api/method/hrms.api.my_details.download_proof?request=${encodeURIComponent(
							frm.doc.name
						)}&kind=${kind}">${esc(kind)} ${__("proof")}</a>`
				)
				.join(" · ");
			const dialog = new frappe.ui.Dialog({
				title: __("Review personal details"),
				size: "large",
				fields: [
					{
						fieldname: "summary",
						fieldtype: "HTML",
						options: `<p>${__(
							"Tick each field you verified. Paired master fields update together. Unticked fields stay unchanged."
						)}</p>${proofLinks}<p>${
							review.stale
								? __(
										"Approved details changed since this request. Ask the employee to correct and resubmit."
								  )
								: ""
						}${review.blockers.map(esc).join("<br>")}</p>`,
					},
					...rows,
					{
						fieldname: "note",
						fieldtype: "Small Text",
						label: __("Note to employee"),
						description: __(
							"Required for corrections or when keeping some fields unchanged. Do not include full identity or bank numbers."
						),
					},
				],
				primary_action_label: __("Approve selected changes"),
				primary_action: async (values) => {
					const selected = review.rows
						.filter((_, i) => values[`approve_${i}`])
						.map((r) => r.key);
					await decide("Approved", selected, values.note || "");
				},
				secondary_action_label: __("Needs correction"),
				secondary_action: async () => {
					await decide("Needs correction", [], dialog.get_value("note") || "");
				},
			});
			let saving = false;
			async function decide(decision, selected, note) {
				if (saving) return;
				saving = true;
				dialog.get_primary_btn().prop("disabled", true);
				try {
					await frappe.call({
						method: "hrms.api.my_details.decide_request",
						args: {
							request: frm.doc.name,
							decision,
							selected,
							note,
							review_token: review.review_token,
						},
					});
					dialog.hide();
					await frm.reload_doc();
				} finally {
					saving = false;
					dialog.get_primary_btn().prop("disabled", Boolean(blocked));
				}
			}
			dialog.show();
			dialog.get_primary_btn().prop("disabled", Boolean(blocked));
		});
	},
});
