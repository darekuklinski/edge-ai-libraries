// Copyright (C) 2024 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { DateTime } from "luxon"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { Badge, Group } from "@mantine/core"
import { IconPaperclip } from "@tabler/icons-react"

import style from "./conversationMessage.module.scss"
import conversationStyles from "../../styles/components/conversation.module.scss"
import { File } from "../../redux/Conversation/Conversation"
import { extractOriginalFilename } from "../../utils/util"

const isTableRow = (line: string) => line.includes("|")

const isTableDelimiter = (line: string) => {
  const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|")
  return line.includes("|") && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
}

const normalizeMarkdownTables = (markdown: string) => {
  const lines = markdown.split("\n")

  for (let index = 0; index < lines.length; index += 1) {
    if (!isTableDelimiter(lines[index])) continue

    let headerIndex = index - 1
    while (headerIndex >= 0 && !lines[headerIndex].trim()) headerIndex -= 1
    if (headerIndex < 0 || !isTableRow(lines[headerIndex])) continue

    if (index - headerIndex > 1) {
      lines.splice(headerIndex + 1, index - headerIndex - 1)
      index = headerIndex + 1
    }

    let rowIndex = index + 1
    while (rowIndex < lines.length) {
      if (lines[rowIndex].trim()) {
        if (!isTableRow(lines[rowIndex])) break
        rowIndex += 1
        continue
      }

      let nextRowIndex = rowIndex
      while (nextRowIndex < lines.length && !lines[nextRowIndex].trim()) {
        nextRowIndex += 1
      }
      if (nextRowIndex >= lines.length || !isTableRow(lines[nextRowIndex])) break

      lines.splice(rowIndex, nextRowIndex - rowIndex)
    }
  }

  return lines.join("\n")
}

const markdownComponents: Components = {
  table: ({ children }) => (
    <div className={style.tableWrapper}>
      <table>{children}</table>
    </div>
  ),
}

export interface ConversationMessageProps {
  message: string
  human: boolean
  date: number
  showBlinkingIndicator?: boolean
  responseTimeMs?: number
  attachments?: File[]
}

export function ConversationMessage({
  human,
  message,
  date,
  showBlinkingIndicator = false,
  responseTimeMs,
  attachments = [],
}: ConversationMessageProps) {
  const dateFormat = () => {
    return DateTime.fromJSDate(new Date(date)).toLocaleString(DateTime.DATETIME_MED)
  }

  const normalizedMessage = normalizeMarkdownTables(message.replace(/\\n/g, "\n"))

  return (
    <div className={`${style.messageRow} ${human ? style.user : style.ai}`}>
      <div className={`${style.messageIcon} ${human ? style.userIcon : style.aiIcon}`}>
        {human ? "U" : "Q"}
      </div>

      <div className={style.messageContent}>
        <div className={`${style.bubble} ${human ? style.userBubble : style.aiBubble}`}>
          {human && attachments.length > 0 && (
            <Group gap="xs" mb="xs">
              {attachments.map((attachment) => (
                <Badge
                  key={`${attachment.bucket_name}/${attachment.file_name}`}
                  size="xs"
                  variant="light"
                  leftSection={<IconPaperclip size={11} />}
                >
                  {extractOriginalFilename(attachment.file_name)}
                </Badge>
              ))}
            </Group>
          )}
          <div className={style.markdownContent}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {normalizedMessage}
            </ReactMarkdown>

            {showBlinkingIndicator && (
              <span
                className={conversationStyles.blinkingIndicator}
                style={{ marginLeft: "4px", display: "inline-block", verticalAlign: "baseline" }}
              />
            )}
          </div>

          {showBlinkingIndicator && (
            <span
              className={conversationStyles.blinkingIndicator}
              style={{ marginLeft: "4px", display: "inline-block", verticalAlign: "baseline" }}
            />
          )}
        </div>

        <div className={style.messageDate}>{dateFormat()}</div>

        {!human && responseTimeMs !== undefined && (
          <div className={style.responseTime}>
            <span className={style.responseDot} />
            <span className={style.responseValue}>
              {(responseTimeMs / 1000).toFixed(2)}s
            </span>
            <span className={style.responseLabel}>response time</span>
          </div>
        )}
      </div>
    </div>
  )
}