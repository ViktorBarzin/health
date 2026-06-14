import { env } from '$env/dynamic/public';
import { filenameFromContentDisposition } from '$lib/export';

const BASE_URL = env.PUBLIC_API_URL || '';

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    const message = typeof body === 'object' && body !== null && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : `API error ${status}`;
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

// On a 429 (rate limited — the request was NOT processed), back off and retry a
// few times rather than letting a transient burst blank a page. Honours a
// numeric `Retry-After`; otherwise exponential backoff with jitter. Safe for
// mutations too: a 429 means the server rejected it before any side effect.
const MAX_RETRIES = 3;

function backoffMs(attempt: number, retryAfter: string | null): number {
  const ra = retryAfter ? Number(retryAfter) : NaN;
  if (Number.isFinite(ra) && ra >= 0) return Math.min(ra * 1000, 8000);
  return Math.min(300 * 2 ** attempt, 4000) + Math.random() * 200;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}${path}`;

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  let response: Response;
  for (let attempt = 0; ; attempt++) {
    response = await fetch(url, {
      ...options,
      headers,
      credentials: 'include',
    });
    if (response.status !== 429 || attempt >= MAX_RETRIES) break;
    await sleep(backoffMs(attempt, response.headers.get('retry-after')));
  }

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = { detail: response.statusText };
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  get<T>(path: string, options?: RequestInit): Promise<T> {
    return apiFetch<T>(path, { ...options, method: 'GET' });
  },

  post<T>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
    return apiFetch<T>(path, {
      ...options,
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },

  put<T>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
    return apiFetch<T>(path, {
      ...options,
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },

  patch<T>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
    return apiFetch<T>(path, {
      ...options,
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },

  delete<T>(path: string, options?: RequestInit): Promise<T> {
    return apiFetch<T>(path, { ...options, method: 'DELETE' });
  },

  /**
   * Download a binary attachment (e.g. the full-data Export ZIP) and trigger a
   * browser save. Streams the response into a Blob, names it from the
   * Content-Disposition header (falling back to a default), and clicks a
   * temporary anchor. Throws {@link ApiError} on a non-2xx response so the UI
   * can surface a message.
   */
  async download(path: string, options?: RequestInit): Promise<void> {
    const url = `${BASE_URL}${path}`;
    const response = await fetch(url, {
      ...options,
      method: 'GET',
      credentials: 'include',
    });
    if (!response.ok) {
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        body = { detail: response.statusText };
      }
      throw new ApiError(response.status, body);
    }
    const filename = filenameFromContentDisposition(
      response.headers.get('content-disposition'),
    );
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    try {
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  },

  /** Upload a file via multipart form data (no JSON content-type). */
  upload<T>(path: string, formData: FormData, options?: RequestInit): Promise<T> {
    const url = `${BASE_URL}${path}`;
    return fetch(url, {
      ...options,
      method: 'POST',
      body: formData,
      credentials: 'include',
    }).then(async (response) => {
      if (!response.ok) {
        let body: unknown;
        try {
          body = await response.json();
        } catch {
          body = { detail: response.statusText };
        }
        throw new ApiError(response.status, body);
      }
      return response.json() as Promise<T>;
    });
  },
};
