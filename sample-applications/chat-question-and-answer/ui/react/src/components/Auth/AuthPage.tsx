// Copyright (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { FormEvent, useState } from "react";
import { Alert, Button, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import axios from "axios";
import { AUTH_URL } from "../../config";
import client from "../../utils/client";
import classes from "./AuthPage.module.scss";

export type Account = {
  id: number;
  username: string;
  role: "admin" | "standard";
};

type AuthPageProps = {
  onAuthenticated: (account: Account) => void;
};

export function AuthPage({ onAuthenticated }: AuthPageProps) {
  const [isRegistering, setIsRegistering] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    if (isRegistering && password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setIsSubmitting(true);

    try {
      const response = await client.post<Account>(
        `${AUTH_URL}/${isRegistering ? "register" : "login"}`,
        { username, password },
      );
      onAuthenticated(response.data);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(
          !isRegistering &&
            (requestError.response?.status === 401 ||
              requestError.response?.status === 422)
            ? "Invalid username or password."
            : typeof detail === "string"
              ? detail
              : requestError.response?.status === 422
                ? "Check your username and password and try again."
                : "Could not connect to the account service. Please try again.",
        );
      } else {
        setError("Could not connect to the account service. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleMode = () => {
    setIsRegistering((current) => !current);
    setPassword("");
    setConfirmPassword("");
    setError("");
  };

  return (
    <main className={classes.authPage}>
      <form className={classes.authCard} onSubmit={submit}>
        <Title order={1}>{isRegistering ? "Create your account" : "Welcome back"}</Title>
        <Text c="dimmed">
          {isRegistering
            ? "Create an account to save and restore your conversations."
            : "Log in to continue to Chat QnA."}
        </Text>
        <Stack gap="md" mt="md">
          {error && <Alert color="red">{error}</Alert>}
          <TextInput
            label="Username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            minLength={3}
            maxLength={32}
            required
          />
          <PasswordInput
            label="Password"
            autoComplete={isRegistering ? "new-password" : "current-password"}
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            minLength={isRegistering ? 8 : undefined}
            maxLength={128}
            required
          />
          {isRegistering && (
            <PasswordInput
              label="Retype password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.currentTarget.value)}
              minLength={8}
              maxLength={128}
              required
            />
          )}
          <Button type="submit" loading={isSubmitting}>
            {isRegistering ? "Create account" : "Log in"}
          </Button>
          <Text ta="center" size="sm">
            {isRegistering ? "Already have an account?" : "New to Chat QnA?"}{" "}
            <button className={classes.modeToggle} type="button" onClick={toggleMode}>
              {isRegistering ? "Log in" : "Create an account"}
            </button>
          </Text>
        </Stack>
      </form>
    </main>
  );
}
