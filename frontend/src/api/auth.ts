import { apiClient } from "./client";
import type { CurrentUser } from "./types";

export function login(
  email: string,
  password: string,
): Promise<{ access_token: string }> {
  return apiClient.post("/auth/login", { email, password });
}

export function fetchCurrentUser(): Promise<CurrentUser> {
  return apiClient.get("/me");
}
