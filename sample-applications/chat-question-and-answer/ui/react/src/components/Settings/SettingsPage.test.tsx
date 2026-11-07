import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";
import client from "../../utils/client";

vi.mock("../../utils/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.get).mockResolvedValue({
      data: { configured: false },
    } as never);
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
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requires matching new passwords before saving", async () => {
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.change(screen.getByLabelText(/Current password/), {
      target: { value: "current-password" },
    });
    fireEvent.change(screen.getByLabelText(/^New password/), {
      target: { value: "new-password" },
    });
    fireEvent.change(screen.getByLabelText(/Confirm new password/), {
      target: { value: "different-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));

    expect(
      await screen.findByText("New password and confirmation do not match."),
    ).toBeTruthy();
    expect(client.post).not.toHaveBeenCalled();
  });

  it("submits current and new passwords and shows success", async () => {
    vi.mocked(client.post).mockResolvedValue({ data: { status: "success" } } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.change(screen.getByLabelText(/Current password/), {
      target: { value: "current-password" },
    });
    fireEvent.change(screen.getByLabelText(/^New password/), {
      target: { value: "new-password" },
    });
    fireEvent.change(screen.getByLabelText(/Confirm new password/), {
      target: { value: "new-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));

    await waitFor(() => {
      expect(client.post).toHaveBeenCalledWith(
        expect.stringContaining("/auth/change-password"),
        {
          current_password: "current-password",
          new_password: "new-password",
        },
      );
    });
    expect(await screen.findByText("Your password has been changed.")).toBeTruthy();
  });

  it("returns to the chat when requested", () => {
    const onBack = vi.fn();
    render(
      <MantineProvider>
        <SettingsPage onBack={onBack} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("saves a Hugging Face token without retrieving its value", async () => {
    vi.mocked(client.put).mockResolvedValue({ data: { status: "success" } } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Hugging Face" }));
    fireEvent.change(await screen.findByPlaceholderText("hf_…"), {
      target: { value: "hf_secret-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save token" }));

    await waitFor(() => {
      expect(client.put).toHaveBeenCalledWith(
        expect.stringContaining("/auth/huggingface-token"),
        { token: "hf_secret-token" },
      );
    });
    expect(await screen.findByText("Your Hugging Face token has been saved securely.")).toBeTruthy();
    expect(
      screen.getByPlaceholderText("Enter a new token to replace it"),
    ).toHaveProperty("value", "");
  });

  it("removes a previously saved Hugging Face token", async () => {
    vi.mocked(client.get).mockResolvedValue({
      data: { configured: true },
    } as never);
    vi.mocked(client.delete).mockResolvedValue({ data: { status: "success" } } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Hugging Face" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove token" }));

    await waitFor(() => {
      expect(client.delete).toHaveBeenCalledWith(
        expect.stringContaining("/auth/huggingface-token"),
      );
    });
    expect(await screen.findByText("Your saved Hugging Face token has been removed.")).toBeTruthy();
  });

  it("lists available models by task", async () => {
    vi.mocked(client.get).mockResolvedValue({
      data: {
        models: [
          {
            id: "llm-model",
            model_name: "org/chat-model",
            display_name: "chat-model",
            task: "llm",
            status: "ready",
            is_default: true,
            artifact_location: "int8/chat-model",
            metadata: { device: "GPU", precision: "int8" },
          },
          {
            id: "embedding-model",
            model_name: "org/embed-model",
            display_name: "embed-model",
            task: "embedding",
            status: "ready",
            is_default: false,
            artifact_location: "int8/embed-model",
            metadata: { device: "CPU", precision: "int8" },
          },
        ],
      },
    } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Models" }));

    expect(await screen.findByText("LLM")).toBeTruthy();
    expect(screen.getByText("Reranker / Embedding")).toBeTruthy();
    expect(screen.getByText("chat-model")).toBeTruthy();
    expect(screen.getByText("embed-model")).toBeTruthy();
    const llmTable = screen.getAllByRole("table")[0];
    expect(llmTable.getAttribute("data-with-table-border")).toBe("true");
    expect(
      llmTable.querySelector("th")?.getAttribute("data-with-column-border"),
    ).toBe("true");
    expect(screen.getByRole("main").className).toContain("settingsPage");
  });

  it("shows user administration only to admins and promotes standard accounts", async () => {
    vi.mocked(client.get).mockResolvedValue({
      data: {
        users: [
          { id: 1, username: "admin", role: "admin" },
          { id: 2, username: "member", role: "standard" },
        ],
      },
    } as never);
    vi.mocked(client.put).mockResolvedValue({
      data: { id: 2, username: "member", role: "admin" },
    } as never);
    vi.mocked(client.post).mockResolvedValue({
      data: { id: 3, username: "new-admin", role: "admin" },
    } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} isAdmin currentUserId={1} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Admin" }));
    expect(await screen.findByText("Create administrator account")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Promote to admin" }));

    await waitFor(() => {
      expect(client.put).toHaveBeenCalledWith(
        expect.stringContaining("/admin/users/2/role"),
        { role: "admin" },
      );
    });

    fireEvent.change(screen.getByLabelText(/^Username/), {
      target: { value: "new-admin" },
    });
    fireEvent.change(screen.getByLabelText(/^Temporary password/), {
      target: { value: "secure-password" },
    });
    fireEvent.change(screen.getByLabelText(/^Confirm password/), {
      target: { value: "secure-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create admin account" }));

    await waitFor(() => {
      expect(client.post).toHaveBeenCalledWith(
        expect.stringContaining("/admin/users"),
        { username: "new-admin", password: "secure-password" },
      );
    });
  });

  it("does not render the admin tab for standard accounts", () => {
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    expect(screen.queryByRole("tab", { name: "Admin" })).toBeNull();
  });

  it("lets admins remove an installed non-default model", async () => {
    vi.mocked(client.get).mockResolvedValue({
      data: {
        models: [
          {
            id: "installed-model",
            model_name: "org/model",
            display_name: "model",
            task: "llm",
            status: "ready",
            is_default: false,
            artifact_location: "int8/org/model",
            metadata: { device: "CPU", precision: "int8" },
          },
        ],
      },
    } as never);
    vi.mocked(client.delete).mockResolvedValue({ data: { status: "success" } } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} isAdmin />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Models" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove model" }));

    await waitFor(() => {
      expect(client.delete).toHaveBeenCalledWith(
        expect.stringContaining("/settings/models"),
        { data: { model_id: "installed-model" } },
      );
    });
  });

  it("submits a Hugging Face model request with conversion settings", async () => {
    vi.mocked(client.get).mockResolvedValue({ data: { models: [] } } as never);
    vi.mocked(client.post).mockResolvedValue({ data: { status: "downloading" } } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Models" }));
    fireEvent.change(
      await screen.findByPlaceholderText("deepseek-ai/dspark_qwen3_4b_block7"),
      { target: { value: "deepseek-ai/dspark_qwen3_4b_block7" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Request model" }));

    await waitFor(() => {
      expect(client.post).toHaveBeenCalledWith(
        expect.stringContaining("/settings/models"),
        {
          model_name: "deepseek-ai/dspark_qwen3_4b_block7",
          task: "llm",
          device: "CPU",
          precision: "int8",
          is_ovms: true,
        },
      );
    });
    expect(
      await screen.findByText(
        "A request to add deepseek-ai/dspark_qwen3_4b_block7 was submitted.",
      ),
    ).toBeTruthy();
  });

  it("sets a ready model as the task default", async () => {
    vi.mocked(client.get).mockResolvedValue({
      data: {
        models: [
          {
            id: "embedding-model",
            model_name: "org/embed-model",
            display_name: "embed-model",
            task: "embedding",
            status: "ready",
            is_default: false,
            artifact_location: "int8/embed-model",
            metadata: { device: "CPU", precision: "int8" },
          },
        ],
      },
    } as never);
    vi.mocked(client.put).mockResolvedValue({ data: { status: "success" } } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Models" }));
    fireEvent.click(await screen.findByRole("button", { name: "Set default" }));

    await waitFor(() => {
      expect(client.put).toHaveBeenCalledWith(
        expect.stringContaining("/settings/models/default"),
        { model_id: "embedding-model" },
      );
    });
    expect(
      await screen.findByText("embed-model is now the default embedding model."),
    ).toBeTruthy();
  });

  it("opens a scrollable failure log from the model notification", async () => {
    vi.mocked(client.get).mockResolvedValue({
      data: {
        models: [
          {
            id: "failed-model",
            model_name: "org/failed-model",
            display_name: "failed-model",
            task: "llm",
            status: "failed",
            is_default: false,
            artifact_location: null,
            metadata: {
              requested_at: "2025-01-01T00:00:00Z",
              logs: "conversion failed: invalid graph",
            },
          },
        ],
      },
    } as never);
    render(
      <MantineProvider>
        <SettingsPage onBack={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Models" }));
    fireEvent.click(await screen.findByRole("button", { name: "View failure log" }));

    expect(await screen.findByText("Failure details: failed-model")).toBeTruthy();
    expect(screen.getByText("conversion failed: invalid graph")).toBeTruthy();
  });
});
