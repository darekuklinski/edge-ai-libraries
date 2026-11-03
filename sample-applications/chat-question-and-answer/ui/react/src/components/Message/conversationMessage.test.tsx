import { render } from "@testing-library/react"
import { describe, expect, test } from "vitest"
import { ConversationMessage } from "./conversationMessage"

describe("ConversationMessage markdown", () => {
  test("renders tables whose rows are separated by blank lines", () => {
    const message = [
      "## Saga gier Resident Evil",
      "",
      "### Główne serie",
      "",
      "| Seria | Kluczowe tytuły | Platformy |",
      "",
      "|-------|-----------------|-----------|",
      "",
      "| **Seria główna** | *Requiem*, *Village* | PS5, PC |",
      "",
      "| **Revelations** | *Revelations* (2013) | PC, PS3 |",
    ].join("\\n")

    const { container } = render(
      <ConversationMessage message={message} human={false} date={0} />,
    )

    const table = container.querySelector("table")
    expect(table).not.toBeNull()
    expect(table?.parentElement?.className).toContain("tableWrapper")
    expect(table?.querySelectorAll("tbody tr")).toHaveLength(2)
    expect(table?.querySelector("th")?.textContent).toBe("Seria")
    expect(table?.querySelector("strong")?.textContent).toBe("Seria główna")
    expect(container.querySelectorAll("p")).toHaveLength(0)
  })
})
