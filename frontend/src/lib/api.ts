import { env } from '$env/dynamic/public';

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

  delete<T>(path: string, options?: RequestInit): Promise<T> {
    return apiFetch<T>(path, { ...options, method: 'DELETE' });
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
