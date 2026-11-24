import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import { MantineProvider } from "@mantine/core";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { beforeEach, describe, expect, test, vi } from "vitest";
import Conversation from "./Conversation";
import conversationReducer, {
  replaceConversations,
  setSelectedConversationId,
} from "../../redux/Conversation/ConversationSlice";
import { MessageRole } from "../../redux/Conversation/Conversation";
import client from "../../utils/client";

const { fetchEventSourceMock } = vi.hoisted(() => ({
  fetchEventSourceMock: vi.fn(async (_url: string, options: any) => {
    await options.onopen(
      new Response(null, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    options.onclose();
  }),
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));
vi.mock("./ConversationSideBar", () => ({
  ConversationSideBar: ({ onNewConversation }: { onNewConversation: () => void }) => (
    <button onClick={onNewConversation}>New chat</button>
  ),
}));
vi.mock("../Drawer/DataSource", () => ({
  default: () => null,
}));
vi.mock("../../utils/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

const indexedFiles = [
  { file_name: "doc_Report_a1b2.pdf", bucket_name: "default" },
];

class TestResizeObserver implements ResizeObserver {
  constructor(_callback: ResizeObserverCallback) {}
  observe(_target: Element, _options?: ResizeObserverOptions) {}
  unobserve(_target: Element) {}
  disconnect() {}
}

const mockAxiosResponse = (data: unknown) =>
  ({ data, status: 200 }) as Awaited<ReturnType<typeof client.get>>;

const renderConversation = () => {
  const store = configureStore({
    reducer: { conversationReducer },
  });
  return { store, ...render(
    <Provider store={store}>
      <MantineProvider>
        <Conversation title="Chat QnA" />
      </MantineProvider>
    </Provider>,
  ) };
};

const sendQuestion = async (question: string) => {
  fireEvent.change(screen.getByPlaceholderText("Ask a question..."), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
  await waitFor(() => expect(fetchEventSourceMock).toHaveBeenCalled());
  return JSON.parse(fetchEventSourceMock.mock.calls[0][1].body);
};

describe("conversation file attachments", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.ResizeObserver = TestResizeObserver;
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockImplementation((media: string) => ({
        matches: false,
        media,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: {
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    vi.mocked(client.get).mockImplementation(async (url) =>
      mockAxiosResponse(
        url.includes("/documents")
          ? indexedFiles
          : url.endsWith("/models")
            ? {
                models: [{
                  id: "test-model",
                  model_name: "test-model",
                  display_name: "test-model",
                  task: "llm",
                  is_default: true,
                }, {
                  id: "other-model",
                  model_name: "org/other-model",
                  display_name: "other-model",
                  task: "llm",
                  is_default: false,
                }],
              }
          : { llm_model: "test-model" },
      ),
    );
    vi.mocked(client.put).mockResolvedValue(mockAxiosResponse({}));
    vi.mocked(client.post).mockResolvedValue(
      mockAxiosResponse({
        status: 200,
        message: "Data preparation succeeded",
        files: [{ file_name: "doc_Uploaded-file_c3d4.pdf", bucket_name: "default" }],
      }),
    );
    localStorage.clear();
  });

  test("attaches a local upload to only the submitted question", async () => {
    const { container } = renderConversation();
    fireEvent.click(screen.getByRole("button", { name: "Attach files" }));

    const fileInput = container.querySelector('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, {
      target: { files: [new File(["document"], "Uploaded-file.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload and attach" }));

    await screen.findByText("Uploaded-file.pdf");
    const request = await sendQuestion("Summarize the attachment");
    expect(request.attachments).toEqual([
      { file_name: "doc_Uploaded-file_c3d4.pdf", bucket_name: "default" },
    ]);
    expect(request.conversation_messages.at(-1).content).toBe("Summarize the attachment");
  });

  test("attaches an indexed library file and sends it with the question", async () => {
    renderConversation();
    fireEvent.click(screen.getByRole("button", { name: "Attach files" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Report.pdf" }));

    const request = await sendQuestion("What is in the report?");
    expect(request.attachments).toEqual(indexedFiles);
  });

  test("sends no attachment identifiers when no file is selected", async () => {
    renderConversation();
    const request = await sendQuestion("What is machine learning?");

    expect(request.attachments).toEqual([]);
    expect(request.conversation_id).toBeTruthy();
  });

  test("chooses a model before the first message and hides the selector afterward", async () => {
    renderConversation();
    fireEvent.click(await screen.findByRole("combobox", { name: "Language model" }));
    fireEvent.click(await screen.findByRole("option", { name: "other-model" }));
    expect(client.put).not.toHaveBeenCalled();

    const request = await sendQuestion("Use a different model");
    expect(client.put).toHaveBeenCalledWith(
      expect.stringMatching(new RegExp(`/conversations/${request.conversation_id}/model$`)),
      { model_id: "other-model" },
    );
    expect(vi.mocked(client.put).mock.invocationCallOrder[0])
      .toBeLessThan(fetchEventSourceMock.mock.invocationCallOrder[0]);
    expect(screen.queryByRole("combobox", { name: "Language model" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.getByRole("combobox", { name: "Language model" })).toHaveValue("test-model");
  });

  test("hides the selector for restored conversations with messages, but shows it for empty ones", async () => {
    const { store } = renderConversation();
    await screen.findByRole("combobox", { name: "Language model" });
    act(() => store.dispatch(replaceConversations([
      { conversationId: "empty", modelId: "test-model", Messages: [] },
      {
        conversationId: "started",
        modelId: "other-model",
        Messages: [{ role: MessageRole.User, content: "Hello", time: 1 }],
      },
    ])));
    expect(screen.queryByRole("combobox", { name: "Language model" })).toBeNull();
    act(() => store.dispatch(setSelectedConversationId("empty")));
    expect(screen.getByRole("combobox", { name: "Language model" })).toHaveValue("test-model");
  });

  test("hides the selector while the first response is still streaming", async () => {
    fetchEventSourceMock.mockImplementationOnce(async () => new Promise<void>(() => {}));
    renderConversation();
    await screen.findByRole("combobox", { name: "Language model" });
    await sendQuestion("Hello");
    expect(screen.queryByRole("combobox", { name: "Language model" })).toBeNull();
  });

  test("keeps the first message and selection available if saving the model fails", async () => {
    vi.mocked(client.put).mockRejectedValueOnce(new Error("Cannot save model"));
    renderConversation();
    await screen.findByRole("combobox", { name: "Language model" });
    fireEvent.change(screen.getByPlaceholderText("Ask a question..."), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(client.put).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("button", { name: "Send question" })).toBeEnabled());
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText("Ask a question...")).toHaveValue("Hello");
    expect(screen.getByRole("combobox", { name: "Language model" })).toBeEnabled();
  });
});
