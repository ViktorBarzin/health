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

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}${path}`;

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
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
