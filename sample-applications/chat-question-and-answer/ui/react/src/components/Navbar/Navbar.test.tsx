import { fireEvent, render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Navbar } from "./Navbar";

describe("Navbar", () => {
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

  it("offers settings from the username menu", async () => {
    const onSettings = vi.fn();
    render(
      <MantineProvider>
        <Navbar username="sample-user" onSettings={onSettings} onLogout={vi.fn()} />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "sample-user" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Settings" }));

    expect(onSettings).toHaveBeenCalledOnce();
  });
});
