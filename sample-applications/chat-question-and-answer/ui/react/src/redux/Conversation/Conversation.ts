// Copyright (C) 2024 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

export type ConversationRequest = {
  conversationId: string;
  userPrompt: Message;
  attachments?: File[];
};
export enum MessageRole {
  Assistant = "assistant",
  User = "user",
  System = "system",
}

export interface Message {
  role: MessageRole;
  content: string;
  time: number;
  conversationId?: string;
  responseTimeMs?: number;
  attachments?: File[];
}

export interface File {
  file_name: string;
  bucket_name: string;
}

export interface FileUploadResponse {
  status: number;
  message: string;
  files: File[];
}

export interface Conversation {
  conversationId: string;
  title?: string;
  modelId?: string;
  Messages: Message[];
  responseStatus?: boolean;
}

export interface ChatModel {
  id: string;
  model_name: string;
  display_name: string;
  task: string;
  is_default: boolean;
}

export interface ConversationReducer {
  selectedConversationId: string;
  conversations: Conversation[];
  onGoingResults: { [conversationId: string]: string };
  modelName: string;
  models: ChatModel[];
  files: File[];
  links: string[];
  isGenerating: { [conversationId: string]: boolean };
  isWaitingForFirstToken: { [conversationId: string]: boolean };
  isUploading: boolean;
}
