import { fireEvent, render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const mocks = vi.hoisted(() => ({
  dispatch: vi.fn(),
  get: vi.fn(),
}));

vi.mock("./redux/store", () => ({
  useAppDispatch: () => mocks.dispatch,
  useAppSelector: () => [],
}));

vi.mock("./redux/Conversation/ConversationSlice", () => ({
  clearConversations: () => ({ type: "clear" }),
  persistConversationHistory: () => ({ type: "persist" }),
  restoreConversationHistory: () => ({ type: "restore" }),
}));

vi.mock("./utils/client", () => ({
  default: {
    get: mocks.get,
    post: vi.fn(),
  },
}));

vi.mock("./components/Auth/AuthPage", () => ({
  AuthPage: () => <div>Authentication page</div>,
}));

vi.mock("./components/Navbar/Navbar", () => ({
  Navbar: ({ onSettings }: { onSettings: () => void }) => (
    <button onClick={onSettings}>Settings</button>
  ),
}));

vi.mock("./components/Conversation/Conversation", () => ({
  default: () => <div>Conversation</div>,
}));

vi.mock("./components/Metrics/MetricsPanel", () => ({
  MetricsPanel: () => <div>Metrics</div>,
}));

vi.mock("./components/Settings/SettingsPage", () => ({
  SettingsPage: () => <div>Settings page</div>,
}));

describe("App inference status", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    mocks.dispatch.mockImplementation((action: { type?: string }) => ({
      unwrap: () =>
        action.type === "restore" ? Promise.resolve([]) : Promise.resolve(),
    }));
    mocks.get.mockImplementation((url: string) => {
      if (url.endsWith("/auth/me")) {
        return Promise.resolve({
          data: { id: 1, username: "admin" },
        });
      }
      if (url.endsWith("/health")) {
        return Promise.reject(new Error("Inference service unavailable"));
      }
      return Promise.resolve({ data: {} });
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("explains an inference outage and opens settings", async () => {
    render(
      <MantineProvider>
        <App />
      </MantineProvider>,
    );

    expect(
      await screen.findByText(/Chat and document search are unavailable/),
    ).toBeTruthy();
    expect(
      screen.getByText(/Settings → Hugging Face.*Settings → Models/),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    expect(screen.getByText("Settings page")).toBeTruthy();
  });
});
