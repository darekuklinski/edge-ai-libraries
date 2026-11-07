// Copyright (C) 2024 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { ChangeEvent, KeyboardEvent, useEffect, useRef, useState } from 'react'
import styleClasses from "../../styles/components/conversation.module.scss"
import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Divider,
  FileInput,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Textarea,
  rem,
} from '@mantine/core'
import { IconArrowRight, IconPaperclip, IconX } from '@tabler/icons-react'
import {
  conversationSelector,
  doConversation,
  newConversation,
  fetchModelName,
  fetchAvailableModels,
  setConversationModel,
  fetchInitialFiles,
  uploadFile,
} from '../../redux/Conversation/ConversationSlice'
import { ConversationMessage } from '../Message/conversationMessage'
import { useAppDispatch, useAppSelector } from '../../redux/store'
import { File as DataSourceFile, Message, MessageRole } from '../../redux/Conversation/Conversation'
import { extractOriginalFilename, getCurrentTimeStamp } from '../../utils/util'
import { useDisclosure } from '@mantine/hooks'
import DataSource from '../Drawer/DataSource'
import { ConversationSideBar } from './ConversationSideBar'
import { notifications } from '@mantine/notifications'
import { MAX_FILE_SIZE, plainAcceptedFormat } from '../../utils/constant'


type ConversationProps = {
  title:string
}

const Conversation = ({ title }: ConversationProps) => {

  title = title //fix this
  const [prompt, setPrompt] = useState<string>("")
  const [hasLLMResponse, setHasLLMResponse] = useState<boolean>(false)
  const [attachmentPickerOpened, setAttachmentPickerOpened] = useState(false)
  const [localFile, setLocalFile] = useState<globalThis.File | null>(null)
  const [pendingAttachments, setPendingAttachments] = useState<DataSourceFile[]>([])
  const [fileListLoading, setFileListLoading] = useState(false)
  const [fileListError, setFileListError] = useState("")
  const [modelSelectionPending, setModelSelectionPending] = useState(false)
  const promptInputRef = useRef<HTMLTextAreaElement>(null)
  const [fileUploadOpened, { close: closeFileUpload }] = useDisclosure(false);

  const {
    conversations,
    onGoingResults,
    selectedConversationId,
    modelName,
    models,
    isGenerating,
    files,
    isUploading,
    isWaitingForFirstToken,
  } = useAppSelector(conversationSelector)
  const dispatch = useAppDispatch();
  const selectedConversation = conversations.find((x: any) => x.conversationId === selectedConversationId)
  const isAnyConversationWaitingForFirstToken = Object.values(isWaitingForFirstToken).some(Boolean)

  const selectedModel =
    models.find((model) => model.id === selectedConversation?.modelId) ??
    models.find((model) => model.is_default);
  const displayedModelName = selectedModel?.display_name ?? modelName;
  const LLM_MODEL_URL = `https://huggingface.co/${selectedModel?.model_name ?? modelName}`;

  const scrollViewport = useRef<HTMLDivElement>(null)

  const toSend = "Enter"

  // Fetch model name
  useEffect(() => {
    dispatch(fetchModelName(undefined));
    dispatch(fetchAvailableModels());
  }, [dispatch]);

  // Check if we have any LLM responses to show model name
  useEffect(() => {
    if (selectedConversation && selectedConversation.Messages.length > 0 &&
      selectedConversation.Messages.some((msg: any) => msg.role === MessageRole.Assistant)) {
      setHasLLMResponse(true);
    } else {
      setHasLLMResponse(false); // for new conversation do not display model name
    }
  }, [selectedConversation?.Messages]);

  useEffect(() => {
    if (!attachmentPickerOpened) {
      return
    }
    setFileListLoading(true)
    setFileListError("")
    void dispatch(fetchInitialFiles())
      .unwrap()
      .catch(() => setFileListError("Could not load the indexed files. Try again."))
      .finally(() => setFileListLoading(false))
  }, [attachmentPickerOpened, dispatch])


  const sameFile = (left: DataSourceFile, right: DataSourceFile) =>
    left.file_name === right.file_name && left.bucket_name === right.bucket_name

  const handleSubmit = () => {
    if (!prompt.trim() || isUploading || modelSelectionPending) {
      return
    }

    const userPrompt: Message = {
      role: MessageRole.User,
      content: prompt,
      time: getCurrentTimeStamp(),
      attachments: pendingAttachments,
    };
    const submittedAttachments = [...pendingAttachments]
    const submission = dispatch(doConversation({
      conversationId: selectedConversationId,
      userPrompt,
      attachments: submittedAttachments,
    }))
    setPendingAttachments((current) =>
      current.filter((file) => !submittedAttachments.some((submitted) => sameFile(file, submitted))),
    )
    void submission.unwrap().catch(() => {
      setPendingAttachments((current) => [
        ...current,
        ...submittedAttachments.filter(
          (submitted) => !current.some((file) => sameFile(file, submitted)),
        ),
      ])
    })
    setAttachmentPickerOpened(false)
    setPrompt("")
  }

  const scrollToBottom = () => {
    scrollViewport.current!.scrollTo({ top: scrollViewport.current!.scrollHeight })
  }

  useEffect(() => {
    scrollToBottom()
  }, [onGoingResults?.[selectedConversationId], selectedConversation?.Messages])

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!event.shiftKey && event.key === toSend) {
      event.preventDefault()
      handleSubmit()
    }
  }


  const handleNewConversation = () => {
    dispatch(newConversation())
  }

  const handleModelChange = (modelId: string | null) => {
    if (!selectedConversationId || !modelId) {
      return;
    }
    setModelSelectionPending(true);
    void dispatch(setConversationModel({
      conversationId: selectedConversationId,
      modelId,
    })).unwrap().catch((error: unknown) => {
      notifications.show({
        color: "red",
        title: "Model selection could not be saved",
        message: error instanceof Error ? error.message : "Please try again.",
      });
    }).finally(() => setModelSelectionPending(false));
  }

  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    setPrompt(event.currentTarget.value)
  }

  const handleAttachmentPickerChange = (opened: boolean) => {
    setAttachmentPickerOpened(opened)
  }

  const handleUploadAndAttach = async () => {
    if (!localFile) {
      return
    }

    if (localFile.size > MAX_FILE_SIZE * 1024 * 1024) {
      notifications.show({
        color: "red",
        title: "File size exceeded",
        message: `Choose a file smaller than ${MAX_FILE_SIZE} MB.`,
      })
      setLocalFile(null)
      return
    }

    try {
      const response = await dispatch(uploadFile({ file: localFile })).unwrap()
      const uploadedFiles = response.files
      if (!uploadedFiles?.length) {
        throw new Error("The upload completed, but DataPrep did not return the indexed file identifier.")
      }

      setPendingAttachments((current) => [
        ...current,
        ...uploadedFiles.filter(
          (uploaded) => !current.some((file) => sameFile(file, uploaded)),
        ),
      ])
      setLocalFile(null)
      dispatch(fetchInitialFiles())
    } catch (error) {
      const message = error instanceof Error ? error.message : "The file could not be attached."
      notifications.show({ color: "red", message })
    }
  }

  const toggleLibraryAttachment = (file: DataSourceFile, checked: boolean) => {
    setPendingAttachments((current) => {
      if (checked) {
        return current.some((attachment) => sameFile(attachment, file))
          ? current
          : [...current, file]
      }
      return current.filter((attachment) => !sameFile(attachment, file))
    })
  }
  return (
    <div className={styleClasses.conversationWrapper}>
      <ConversationSideBar onNewConversation={handleNewConversation} />
      <div className={styleClasses.conversationContent}>
        <div className={styleClasses.conversationContentMessages}>
          <div className={styleClasses.historyContainer} ref={scrollViewport}>

            {!selectedConversation && (
              <div className={styleClasses.emptyState}>
                <div className={styleClasses.emptyStateTitle}>
                  What are you working on?
                </div>

                <div className={styleClasses.emptyStateSubtitle}>
                  Ask a question to get started
                </div>
              </div>
            )}

            {selectedConversation?.Messages.map((message: any, index: number) => {
              return (
                <ConversationMessage
                  key={`${message.role}_${message.time}_${index}`}
                  date={message.time * 1000}
                  human={message.role == MessageRole.User}
                  message={message.content}
                  responseTimeMs={message.responseTimeMs}
                  attachments={message.attachments}
                />
              )
            })}

            {/* Show ongoing AI response with blinking indicator inline with streaming text */}
            {(isGenerating[selectedConversationId] || onGoingResults?.[selectedConversationId]) && (
              <ConversationMessage
                key={`ongoing_${selectedConversationId}`}
                date={Date.now()}
                human={false}
                message={onGoingResults?.[selectedConversationId] || ""}
                showBlinkingIndicator={isGenerating[selectedConversationId]}
              />
            )}

            {hasLLMResponse && (
              <div style={{ textAlign: 'right', paddingTop: '12px' }}>
                <Anchor href={LLM_MODEL_URL} target="_blank" size="xs" style={{ textDecoration: 'underline' }}>
                  {displayedModelName}
                </Anchor>
              </div>
            )}
          </div>

          <div className={styleClasses.conversationActions}>
            {selectedConversation && models.length > 0 && (
              <Select
                label="Language model"
                aria-label="Language model"
                value={selectedModel?.id ?? null}
                data={models.map((model) => ({
                  value: model.id,
                  label: model.display_name,
                }))}
                onChange={handleModelChange}
                disabled={
                  modelSelectionPending ||
                  Boolean(isGenerating[selectedConversationId])
                }
                maw={320}
                mb="sm"
              />
            )}
            {pendingAttachments.length > 0 && (
              <Group gap="xs" mb="xs">
                {pendingAttachments.map((file) => (
                  <Badge
                    key={`${file.bucket_name}/${file.file_name}`}
                    variant="light"
                    rightSection={
                      <ActionIcon
                        size="xs"
                        variant="subtle"
                        aria-label={`Remove ${extractOriginalFilename(file.file_name)}`}
                        onClick={() => toggleLibraryAttachment(file, false)}
                      >
                        <IconX size={12} />
                      </ActionIcon>
                    }
                  >
                    {extractOriginalFilename(file.file_name)}
                  </Badge>
                ))}
              </Group>
            )}
            <Textarea
              classNames={{
                root: styleClasses.promptRoot,
                input: styleClasses.promptInput,
                section: styleClasses.promptSection,
              }}
              placeholder="Ask a question..."
              ref={promptInputRef}
              onKeyDown={handleKeyDown}
              onChange={handleChange}
              value={prompt}
              disabled={modelSelectionPending}
              autosize
              minRows={1}
              maxRows={4}
              leftSectionWidth={42}
              leftSection={
                <div className={styleClasses.attachmentPickerAnchor}>
                    <ActionIcon
                      variant="subtle"
                      aria-label="Attach files"
                      title="Attach files"
                      aria-expanded={attachmentPickerOpened}
                      onClick={() => handleAttachmentPickerChange(!attachmentPickerOpened)}
                    >
                      <IconPaperclip style={{ width: rem(18), height: rem(18) }} stroke={1.5} />
                    </ActionIcon>
                  {attachmentPickerOpened && (
                  <div className={styleClasses.attachmentPicker} role="dialog" aria-label="Attach files">
                    <Stack gap="sm">
                      <Text size="sm" fw={600}>Attach files to this question</Text>
                      <FileInput
                        value={localFile}
                        onChange={setLocalFile}
                        accept={plainAcceptedFormat.join(",")}
                        placeholder="Choose a local file"
                        clearable
                      />
                      <Text size="xs" c="dimmed">PDF, TXT, or DOCX; maximum {MAX_FILE_SIZE} MB.</Text>
                      <Button
                        size="xs"
                        onClick={handleUploadAndAttach}
                        disabled={!localFile || isUploading || isAnyConversationWaitingForFirstToken}
                        loading={isUploading}
                      >
                        Upload and attach
                      </Button>
                      <Divider />
                      <Text size="xs" fw={600}>Or choose an indexed file</Text>
                      {fileListLoading ? (
                        <Loader size="sm" />
                      ) : fileListError ? (
                        <Text size="xs" c="red">{fileListError}</Text>
                      ) : files.length === 0 ? (
                        <Text size="xs" c="dimmed">No indexed files are available yet.</Text>
                      ) : (
                        <div className={styleClasses.attachmentFileList}>
                          <Stack gap="xs">
                            {files.map((file) => (
                              <Checkbox
                                key={`${file.bucket_name}/${file.file_name}`}
                                checked={pendingAttachments.some((attachment) => sameFile(attachment, file))}
                                onChange={(event) => toggleLibraryAttachment(file, event.currentTarget.checked)}
                                label={extractOriginalFilename(file.file_name)}
                              />
                            ))}
                          </Stack>
                        </div>
                      )}
                    </Stack>
                  </div>
                  )}
                </div>
              }
              rightSectionWidth={42}
              rightSection={
                <ActionIcon
                  className={styleClasses.sendButton}
                  onClick={handleSubmit}
                  disabled={!prompt.trim() || isUploading || modelSelectionPending}
                  aria-label="Send question"
                  size={28}
                  radius={7}
                  variant="filled"
                >
                  <IconArrowRight style={{ width: rem(18), height: rem(18) }} stroke={1.5} />
                </ActionIcon>
              }
            />
          </div>
        </div>
      </div>
      <DataSource opened={fileUploadOpened} onClose={closeFileUpload} />
    </div >
  )
}
export default Conversation;
