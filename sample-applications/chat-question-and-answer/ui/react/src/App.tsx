// Copyright (C) 2025 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import "./App.scss"
import { useEffect, useRef, useState } from "react"
import { Alert, Button, Center, Loader, MantineProvider, Stack } from "@mantine/core"
import '@mantine/notifications/styles.css';
import Conversation from "./components/Conversation/Conversation"
import { Notifications, notifications } from '@mantine/notifications';
import { Navbar } from "./components/Navbar/Navbar";
import { MetricsPanel } from "./components/Metrics/MetricsPanel"
import { useAppDispatch, useAppSelector } from "./redux/store";
import {
  clearConversations,
  persistConversationHistory,
  restoreConversationHistory,
} from "./redux/Conversation/ConversationSlice";
import { AuthPage, type Account } from "./components/Auth/AuthPage";
import { AUTH_URL } from "./config";
import client from "./utils/client";
import axios from "axios";

const title = "ChatQnA"

function App() {
  const dispatch = useAppDispatch();
  const conversations = useAppSelector(
    (state) => state.conversationReducer.conversations,
  );
  const [account, setAccount] = useState<Account | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [historyReady, setHistoryReady] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const saveErrorShown = useRef(false);

  useEffect(() => {
    void client.get<Account>(`${AUTH_URL}/me`)
      .then((response) => setAccount(response.data))
      .catch((error: unknown) => {
        if (axios.isAxiosError(error) && error.response?.status === 401) {
          setAccount(null);
          return;
        }
        setHistoryError("Could not connect to the account service. Please retry.");
      })
      .finally(() => setCheckingSession(false));
  }, []);

  useEffect(() => {
    if (!account) {
      setHistoryReady(false);
      return;
    }

    let active = true;
    setHistoryReady(false);
    setHistoryError("");
    void dispatch(restoreConversationHistory())
      .unwrap()
      .then(() => {
        if (active) {
          setHistoryReady(true);
        }
      })
      .catch(() => {
        if (active) {
          setHistoryError("Your conversation history could not be loaded.");
        }
      });
    return () => {
      active = false;
    };
  }, [account?.id, dispatch]);

  useEffect(() => {
    if (!account || !historyReady) {
      return;
    }

    const timeout = window.setTimeout(() => {
      const save = saveQueue.current
        .catch(() => undefined)
        .then(() => persistConversationHistory(conversations));
      saveQueue.current = save;
      void save
        .then(() => {
          saveErrorShown.current = false;
        })
        .catch(() => {
          if (!saveErrorShown.current) {
            notifications.show({
              color: "red",
              title: "Chat history could not be saved",
              message:
                "The latest conversation changes could not be saved to the database.",
              autoClose: 7000,
            });
            saveErrorShown.current = true;
          }
        });
    }, 750);

    return () => window.clearTimeout(timeout);
  }, [account, conversations, historyReady]);

  const logout = async () => {
    try {
      await client.post(`${AUTH_URL}/logout`);
      dispatch(clearConversations());
      setAccount(null);
      setHistoryReady(false);
    } catch {
      notifications.show({
        color: "red",
        title: "Could not log out",
        message: "The account service could not end this session. Please try again.",
      });
    }
  };

  const retryHistory = () => {
    if (!account) {
      return;
    }
    setHistoryError("");
    void dispatch(restoreConversationHistory())
      .unwrap()
      .then(() => setHistoryReady(true))
      .catch(() => setHistoryError("Your conversation history could not be loaded."));
  };

  return (
    <MantineProvider>
      <Notifications position="top-right" />

      {checkingSession ? (
        <Center mih="100vh"><Loader /></Center>
      ) : !account ? (
        historyError ? (
          <Center mih="100vh">
            <Stack>
              <Alert color="red">{historyError}</Alert>
              <Button onClick={() => window.location.reload()}>Retry</Button>
            </Stack>
          </Center>
        ) : (
          <AuthPage onAuthenticated={setAccount} />
        )
      ) : !historyReady ? (
        <Center mih="100vh">
          {historyError ? (
            <Stack>
              <Alert color="red">{historyError}</Alert>
              <Button onClick={retryHistory}>Retry</Button>
              <Button variant="subtle" onClick={() => void logout()}>Log out</Button>
            </Stack>
          ) : <Loader />}
        </Center>
      ) : (
        <div className="app-shell">
          <Navbar username={account.username} onLogout={() => void logout()} />
          <div className="chat-container">
            <Conversation title={title} />
          </div>
          <MetricsPanel />
        </div>
      )}
    </MantineProvider>
  )
}

export default App
