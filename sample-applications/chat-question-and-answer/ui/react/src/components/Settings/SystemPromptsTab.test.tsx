import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SystemPromptsTab } from "./SystemPromptsTab";
import { SettingsPage } from "./SettingsPage";
import client from "../../utils/client";

vi.mock("../../utils/client", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

describe("system prompt settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((media: string) => ({
      matches: false, media, addListener: vi.fn(), removeListener: vi.fn(),
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    })));
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true, value: vi.fn(),
    });
    vi.mocked(client.get).mockImplementation(async (url) => ({
      data: url.endsWith("/models")
        ? { models: [{ model_name: "Qwen/Qwen3", display_name: "Qwen3", task: "llm" }] }
        : {
            prompts: [
              { id: "general", name: "General", content: "Base instructions", is_default: true },
              { id: "qwen", name: "Qwen", content: "Qwen instructions", is_default: false },
            ],
            assignments: [{ scope: "family", target: "qwen", prompt_id: "qwen" }],
          },
    }) as never);
    vi.mocked(client.post).mockResolvedValue({ data: {} } as never);
    vi.mocked(client.put).mockResolvedValue({ data: {} } as never);
    vi.mocked(client.delete).mockResolvedValue({ data: {} } as never);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("only exposes the settings tab to administrators", () => {
    const { rerender } = render(<MantineProvider><SettingsPage onBack={vi.fn()} /></MantineProvider>);
    expect(screen.queryByRole("tab", { name: "System prompts" })).toBeNull();
    rerender(<MantineProvider><SettingsPage onBack={vi.fn()} isAdmin /></MantineProvider>);
    expect(screen.getByRole("tab", { name: "System prompts" })).toBeTruthy();
  });

  it("creates and edits prompt instructions", async () => {
    render(<MantineProvider><SystemPromptsTab /></MantineProvider>);
    await screen.findByText("General");
    fireEvent.change(screen.getByLabelText(/Prompt name/), { target: { value: "New prompt" } });
    fireEvent.change(screen.getByLabelText(/System instructions/), { target: { value: "Custom instructions" } });
    fireEvent.click(screen.getByRole("button", { name: "Save prompt" }));
    await waitFor(() => expect(client.post).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/system-prompts$/),
      { name: "New prompt", content: "Custom instructions" },
    ));
    await screen.findByText("System prompt saved.");
    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[1]);
    fireEvent.change(screen.getByLabelText(/System instructions/), { target: { value: "Updated" } });
    fireEvent.click(screen.getByRole("button", { name: "Save prompt" }));
    await waitFor(() => expect(client.put).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/system-prompts\/qwen$/),
      { name: "Qwen", content: "Updated" },
    ));
  });

  it("assigns an exact model and removes a family assignment", async () => {
    render(<MantineProvider><SystemPromptsTab /></MantineProvider>);
    await screen.findByText("General");
    fireEvent.click(screen.getByRole("combobox", { name: "Assignment scope" }));
    fireEvent.click(screen.getByRole("option", { name: "Exact model" }));
    fireEvent.click(screen.getByRole("combobox", { name: "Model" }));
    fireEvent.click(screen.getByRole("option", { name: "Qwen3 (Qwen/Qwen3)" }));
    fireEvent.click(screen.getByRole("combobox", { name: "Assigned system prompt" }));
    fireEvent.click(screen.getByRole("option", { name: "General" }));
    fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
    await waitFor(() => expect(client.put).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/system-prompts\/assignments$/),
      { scope: "model", target: "Qwen/Qwen3", prompt_id: "general" },
    ));
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(client.delete).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/system-prompts\/assignments$/),
      { data: { scope: "family", target: "qwen" } },
    ));
  });

  it("sets a default, confirms deletion, and surfaces failures", async () => {
    render(<MantineProvider><SystemPromptsTab /></MantineProvider>);
    await screen.findByText("General");
    fireEvent.click(screen.getByRole("button", { name: "Set default" }));
    await waitFor(() => expect(client.put).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/system-prompts\/qwen\/default$/),
    ));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText(/Its model and family assignments will also be removed/)).toBeTruthy();
    vi.mocked(client.delete).mockRejectedValueOnce(new Error("failure"));
    fireEvent.click(screen.getByRole("button", { name: "Delete prompt" }));
    expect(await screen.findByText("Could not update system prompt settings. Please try again.")).toBeTruthy();
  });
});
