import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LoginPage } from "./LoginPage";
import { AuthProvider } from "./AuthContext";
import * as authApi from "../api/auth";
import { ApiError } from "../api/client";

describe("LoginPage", () => {
  it("muestra el mensaje de error del backend cuando el login falla", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(
      new ApiError({
        type: "https://sofia.example/errors/invalid-credentials",
        title: "No autenticado",
        status: 401,
        code: "INVALID_CREDENTIALS",
        detail: "Email o contraseña incorrectos",
        request_id: null,
        errors: [],
      }),
    );

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>,
    );

    await userEvent.type(
      screen.getByLabelText(/correo electrónico/i),
      "planner@example.com",
    );
    await userEvent.type(
      screen.getByLabelText(/contraseña/i),
      "wrong-password",
    );
    await userEvent.click(screen.getByRole("button", { name: /acceder/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Email o contraseña incorrectos",
      );
    });
  });
});
