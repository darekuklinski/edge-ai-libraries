import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MantineProvider } from "@mantine/core";
import { AuthPage } from "./AuthPage";
import client from "../../utils/client";

describe("AuthPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((media: string) => ({
        matches: false,
        media,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("allows creating an account and reports the signed-in account", async () => {
    const account = { id: 12, username: "sample-user", role: "standard" as const };
    const post = vi.spyOn(client, "post").mockResolvedValue({ data: account } as never);
    const onAuthenticated = vi.fn();
    render(
      <MantineProvider>
        <AuthPage onAuthenticated={onAuthenticated} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Create an account" }));
    expect(screen.getByRole("heading", { name: "Create your account" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Username/), {
      target: { value: "sample-user" },
    });
    fireEvent.change(screen.getByLabelText(/Password/), {
      target: { value: "secure-password" },
    });
    fireEvent.change(screen.getByLabelText(/Retype password/), {
      target: { value: "secure-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(account));
    expect(post).toHaveBeenCalledWith(
      expect.stringContaining("/auth/register"),
      { username: "sample-user", password: "secure-password" },
    );
  });

  it("does not submit registration when passwords do not match", async () => {
    const post = vi.spyOn(client, "post");
    render(
      <MantineProvider>
        <AuthPage onAuthenticated={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Create an account" }));
    fireEvent.change(screen.getByLabelText(/Username/), {
      target: { value: "sample-user" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/), {
      target: { value: "secure-password" },
    });
    fireEvent.change(screen.getByLabelText(/Retype password/), {
      target: { value: "different-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Passwords do not match.")).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });

  it("shows a login error returned by the API", async () => {
    vi.spyOn(client, "post").mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: "Invalid username or password" } },
    });
    render(
      <MantineProvider>
        <AuthPage onAuthenticated={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.change(screen.getByLabelText(/Username/), {
      target: { value: "sample-user" },
    });
    fireEvent.change(screen.getByLabelText(/Password/), {
      target: { value: "secure-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByText("Invalid username or password")).toBeTruthy();
  });

  it("allows a short existing password on login and hides password policy hints", async () => {
    const post = vi.spyOn(client, "post").mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: [{ msg: "String should have at least 8 characters" }] } },
    });
    render(
      <MantineProvider>
        <AuthPage onAuthenticated={vi.fn()} />
      </MantineProvider>,
    );

    const passwordInput = screen.getByLabelText(/^Password/);
    expect(passwordInput.getAttribute("minlength")).toBeNull();
    fireEvent.change(screen.getByLabelText(/Username/), {
      target: { value: "admin" },
    });
    fireEvent.change(passwordInput, { target: { value: "admin" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        expect.stringContaining("/auth/login"),
        { username: "admin", password: "admin" },
      );
    });
    expect(await screen.findByText("Invalid username or password.")).toBeTruthy();
    expect(screen.queryByText(/8 characters|pattern|minimum/i)).toBeNull();
  });
});
