import type { Handle } from '@sveltejs/kit';

const API_BACKEND = process.env.API_BACKEND_URL || 'http://localhost:8000';

export const handle: Handle = async ({ event, resolve }) => {
	if (event.url.pathname.startsWith('/api/')) {
		const backendUrl = `${API_BACKEND}${event.url.pathname}${event.url.search}`;
		const headers = new Headers(event.request.headers);
		headers.delete('host');

		const resp = await fetch(backendUrl, {
			method: event.request.method,
			headers,
			body:
				event.request.method !== 'GET' && event.request.method !== 'HEAD'
					? event.request.body
					: undefined,
			// @ts-expect-error - duplex is required for streaming request bodies but not yet in all TS types
			duplex: 'half'
		});

		return new Response(resp.body, {
			status: resp.status,
			statusText: resp.statusText,
			headers: resp.headers
		});
	}

	return resolve(event);
};
