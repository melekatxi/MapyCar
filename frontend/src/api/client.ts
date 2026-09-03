// Cliente HTTP mínimo: añade el token de sesión, parsea el formato de error del backend
// (diseño sección 8.1) y expone helpers get/post/put/patch. Nunca decide autorización: el
// backend siempre re-autoriza cada petición (el frontend solo oculta acciones por ergonomía).
const DEFAULT_BASE_URL = "http://localhost:8000/api/v1";

export interface ApiErrorBody {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string;
  request_id: string | null;
  errors: Array<{
    field?: string;
    code?: string;
    row?: number;
    message?: string;
  }>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly body: ApiErrorBody;

  constructor(body: ApiErrorBody) {
    super(body.detail || body.title);
    this.status = body.status;
    this.code = body.code;
    this.body = body;
  }
}

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL;
}

// Almacenamiento tolerante a fallos: navegación privada, cookies bloqueadas o un
// entorno de test sin `localStorage` no deben romper la aplicación, solo la sesión
// no persiste entre recargas.
function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem("sofia_token");
  } catch {
    return null;
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token) {
      window.localStorage.setItem("sofia_token", token);
    } else {
      window.localStorage.removeItem("sofia_token");
    }
  } catch {
    // almacenamiento no disponible: la sesión sigue funcionando solo en memoria
  }
}

let authToken: string | null | undefined;

export function setAuthToken(token: string | null): void {
  authToken = token;
  writeStoredToken(token);
}

export function getAuthToken(): string | null {
  if (authToken === undefined) {
    authToken = readStoredToken();
  }
  return authToken;
}

interface RequestOptions {
  method?: string;
  query?: Record<string, string | undefined>;
  body?: unknown;
  isFormData?: boolean;
  idempotencyKey?: string;
  ifMatch?: string;
}

function buildUrl(
  path: string,
  query?: Record<string, string | undefined>,
): string {
  const url = new URL(getBaseUrl() + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, value);
  }
  return url.toString();
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getAuthToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.idempotencyKey)
    headers["Idempotency-Key"] = options.idempotencyKey;
  if (options.ifMatch) headers["If-Match"] = options.ifMatch;

  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    if (options.isFormData) {
      body = options.body as FormData;
    } else {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }
  }

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const payload = await response.json();
  if (!response.ok) {
    throw new ApiError(payload as ApiErrorBody);
  }
  return payload as T;
}

export const apiClient = {
  get: <T>(path: string, query?: Record<string, string | undefined>) =>
    request<T>(path, { query }),
  post: <T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => request<T>(path, { ...options, method: "POST", body }),
  put: <T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => request<T>(path, { ...options, method: "PUT", body }),
  patch: <T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => request<T>(path, { ...options, method: "PATCH", body }),
};
