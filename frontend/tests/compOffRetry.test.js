import { test } from "node:test"
import assert from "node:assert/strict"
import { submitCompOff } from "../src/utils/compOffRetry.js"

test("retries only aborted transactions with unchanged payload", async () => {
	const calls = []
	const payload = { work_date: "2026-09-06", reason: "Verified work", half_day: 1 }
	const resource = {
		submit: async (params) => {
			calls.push(params)
			if (calls.length < 3) throw { exc_type: "QueryDeadlockError" }
			return { name: "same-request" }
		},
	}
	assert.deepEqual(await submitCompOff(resource, payload), { name: "same-request" })
	assert.equal(calls.length, 3)
	calls.forEach((p) => assert.deepEqual(p, payload))
})
test("does not retry permission, validation or uncertain network failures", async () => {
	for (const exc_type of ["PermissionError", "ValidationError", undefined]) {
		let calls = 0
		const error = { exc_type }
		await assert.rejects(
			submitCompOff(
				{
					submit: async () => {
						calls++
						throw error
					},
				},
				{ name: "request", decision: "Approved" }
			),
			(e) => e === error
		)
		assert.equal(calls, 1)
	}
})
test("bounds repeated aborts to four attempts", async () => {
	let calls = 0
	const error = { exc_type: "QueryDeadlockError" }
	await assert.rejects(
		submitCompOff(
			{
				submit: async () => {
					calls++
					throw error
				},
			},
			{}
		),
		(e) => e === error
	)
	assert.equal(calls, 4)
})
