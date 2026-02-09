import type { Handle } from '@sveltejs/kit';

const API_BACKEND = process.env.API_BACKEND_URL || 'http://localhost:8000';

export const handle: Handle = async ({ event, resolve }) => {
	if (event.url.pathname.startsWith('/api/')) {
		const backendUrl = `${API_BACKEND}${event.url.pathname}${event.url.search}`;
		const headers = new Headers(event.request.headers);
		headers.delete('host');

		const hasBody = event.request.method !== 'GET' && event.request.method !== 'HEAD';

		const fetchOptions: RequestInit = {
			method: event.request.method,
			headers,
			body: hasBody ? event.request.body : undefined,
		};

		// duplex is required for streaming request bodies (e.g. large file uploads)
		// but must only be set when there IS a body
		if (hasBody) {
			// @ts-expect-error - duplex is not yet in all TS types
			fetchOptions.duplex = 'half';
		}

		const resp = await fetch(backendUrl, fetchOptions);

		return new Response(resp.body, {
			status: resp.status,
			statusText: resp.statusText,
			headers: resp.headers,
		});
	}

	return resolve(event);
};
