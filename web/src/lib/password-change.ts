/**
 * The password change in flight, shared by Settings › Account and the shell (NET-358).
 *
 * A request sent with the old cookie just before a change lands can come back 401 after the new
 * cookie is set. The shell waits here before it believes such a 401, so it doesn't send a browser
 * whose change just succeeded to the sign-in page and lose the result.
 */

// Client-only state: only client event handlers may change it (on the server it would be shared by every request)
let inFlight: Promise<void> | null = null;
let succeeded = 0;

// OLD CODE START — NET-358 review: generic over any promise and an `ok` callback, for one caller that sends a fetch
// /** Register a password-change request; when it resolves and `ok(value)` is true, the counter moves. */
// export function trackPasswordChange<T>(request: Promise<T>, ok: (value: T) => boolean): Promise<T> {
// 	const tracked = request.then((value) => {
// 		if (ok(value)) succeeded++;
// 		return value;
// 	});
// OLD CODE END
/** Register a password-change request; when its response is ok, the counter moves. */
export function trackPasswordChange(request: Promise<Response>): Promise<Response> {
	const tracked = request.then((res) => {
		if (res.ok) succeeded++;
		return res;
	});
	const settled = tracked.then(
		() => undefined,
		() => undefined,
	);
	inFlight = settled;
	void settled.then(() => {
		if (inFlight === settled) inFlight = null;
	});
	return tracked;
}

/** Resolves once no password change is in flight; never rejects. */
export async function passwordChangeSettled(): Promise<void> {
	while (inFlight) await inFlight;
}

/** How many password changes have succeeded in this page's life. */
export function passwordChangeCount(): number {
	return succeeded;
}
