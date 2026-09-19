// A deadlock response means Frappe rolled back the entire HTTP transaction.
// Retry only that explicit response; never retry validation, permission, or network errors.
export async function submitCompOff(resource, params) {
	const snapshot = { ...params }
	for (let attempt = 0; attempt < 4; attempt++) {
		try {
			return await resource.submit({ ...snapshot })
		} catch (error) {
			if (error?.exc_type !== "QueryDeadlockError" || attempt === 3) throw error
			await new Promise((resolve) => setTimeout(resolve, 100 * (attempt + 1)))
		}
	}
}
