import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  Group,
  Modal,
  PasswordInput,
  ScrollArea,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import axios from "axios";
import { ADMIN_USERS_URL, AUTH_URL, SETTINGS_MODELS_URL } from "../../config";
import client from "../../utils/client";
import classes from "./SettingsPage.module.scss";

type SettingsPageProps = {
  onBack: () => void;
  isAdmin?: boolean;
  currentUserId?: number;
};

function ChangePasswordTab() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSuccess("");

    if (newPassword !== confirmPassword) {
      setError("New password and confirmation do not match.");
      return;
    }

    setIsSubmitting(true);
    try {
      await client.post(`${AUTH_URL}/change-password`, {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSuccess("Your password has been changed.");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : "Could not change your password. Please try again.",
        );
      } else {
        setError("Could not change your password. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <Stack maw={480} gap="md">
        <Text c="dimmed" size="sm">
          Enter your current password, then choose and confirm a new password.
        </Text>
        {error && <Alert color="red">{error}</Alert>}
        {success && <Alert color="green">{success}</Alert>}
        <PasswordInput
          label="Current password"
          autoComplete="current-password"
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.currentTarget.value)}
          maxLength={128}
          required
        />
        <PasswordInput
          label="New password"
          autoComplete="new-password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.currentTarget.value)}
          minLength={8}
          maxLength={128}
          required
        />
        <PasswordInput
          label="Confirm new password"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.currentTarget.value)}
          minLength={8}
          maxLength={128}
          required
        />
        <Group>
          <Button type="submit" loading={isSubmitting}>
            Change password
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

function HuggingFaceTokenTab() {
  const [token, setToken] = useState("");
  const [isConfigured, setIsConfigured] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const refreshStatus = useCallback(async () => {
    setError("");
    try {
      const response = await client.get<{ configured: boolean }>(
        `${AUTH_URL}/huggingface-token`,
      );
      setIsConfigured(response.data.configured);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : "Could not load token status. Please try again.",
        );
      } else {
        setError("Could not load token status. Please try again.");
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    setIsSubmitting(true);
    try {
      await client.put(`${AUTH_URL}/huggingface-token`, { token });
      setToken("");
      setIsConfigured(true);
      setSuccess("Your Hugging Face token has been saved securely.");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : "Could not save your token. Please try again.",
        );
      } else {
        setError("Could not save your token. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const removeToken = async () => {
    setError("");
    setSuccess("");
    setIsSubmitting(true);
    try {
      await client.delete(`${AUTH_URL}/huggingface-token`);
      setIsConfigured(false);
      setToken("");
      setSuccess("Your saved Hugging Face token has been removed.");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : "Could not remove your token. Please try again.",
        );
      } else {
        setError("Could not remove your token. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Stack maw={520} gap="md">
      <Text c="dimmed" size="sm">
        Save a Hugging Face token for future model downloads. The token is never
        shown again after saving.
      </Text>
      {isLoading ? (
        <Text size="sm">Checking saved token…</Text>
      ) : (
        <Text size="sm" role="status">
          {isConfigured ? "A token is saved." : "No token is saved."}
        </Text>
      )}
      {error && <Alert color="red">{error}</Alert>}
      {success && <Alert color="green">{success}</Alert>}
      <form onSubmit={submit}>
        <Stack gap="md">
          <PasswordInput
            label="Hugging Face API token"
            aria-label="Hugging Face API token"
            autoComplete="new-password"
            value={token}
            onChange={(event) => setToken(event.currentTarget.value)}
            maxLength={4096}
            placeholder={isConfigured ? "Enter a new token to replace it" : "hf_…"}
            required
          />
          <Group>
            <Button type="submit" loading={isSubmitting} disabled={isLoading || !token}>
              Save token
            </Button>
            {isConfigured && (
              <Button
                type="button"
                color="red"
                variant="light"
                loading={isSubmitting}
                onClick={() => void removeToken()}
              >
                Remove token
              </Button>
            )}
          </Group>
        </Stack>
      </form>
    </Stack>
  );
}

type ManagedAccount = {
  id: number;
  username: string;
  role: "admin" | "standard";
};

function AdminManagementTab({ currentUserId }: { currentUserId?: number }) {
  const [users, setUsers] = useState<ManagedAccount[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [updatingUserId, setUpdatingUserId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const loadUsers = useCallback(async () => {
    try {
      const response = await client.get<{ users: ManagedAccount[] }>(ADMIN_USERS_URL);
      setUsers(response.data.users);
      setError("");
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : undefined;
      setError(typeof detail === "string" ? detail : "Could not load user accounts.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const createAdmin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);
    try {
      await client.post(ADMIN_USERS_URL, { username, password });
      setUsername("");
      setPassword("");
      setConfirmPassword("");
      setSuccess(`Administrator account "${username}" was created.`);
      await loadUsers();
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : undefined;
      setError(typeof detail === "string" ? detail : "Could not create the administrator account.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const changeRole = async (user: ManagedAccount) => {
    const role = user.role === "admin" ? "standard" : "admin";
    setError("");
    setSuccess("");
    setUpdatingUserId(user.id);
    try {
      await client.put(`${ADMIN_USERS_URL}/${user.id}/role`, { role });
      setSuccess(`${user.username} is now in the ${role} group.`);
      await loadUsers();
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : undefined;
      setError(typeof detail === "string" ? detail : "Could not update the account group.");
    } finally {
      setUpdatingUserId(null);
    }
  };

  return (
    <Stack gap="xl">
      <Stack gap="xs">
        <Title order={3}>User accounts</Title>
        <Text c="dimmed" size="sm">
          Admins can promote standard users or move administrators back to the standard group.
        </Text>
        {error && <Alert color="red">{error}</Alert>}
        {success && <Alert color="green">{success}</Alert>}
        {isLoading ? (
          <Text size="sm">Loading user accounts…</Text>
        ) : users.length === 0 ? (
          <Text c="dimmed" size="sm">No user accounts found.</Text>
        ) : (
          <Table withTableBorder withColumnBorders>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Username</Table.Th>
                <Table.Th>Group</Table.Th>
                <Table.Th>Action</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {users.map((user) => (
                <Table.Tr key={user.id}>
                  <Table.Td>{user.username}</Table.Td>
                  <Table.Td>
                    <Badge color={user.role === "admin" ? "blue" : "gray"}>
                      {user.role === "admin" ? "Admin" : "Standard"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="xs"
                      variant="light"
                      color={user.role === "admin" ? "gray" : "blue"}
                      loading={updatingUserId === user.id}
                      disabled={user.id === currentUserId && user.role === "admin"}
                      onClick={() => void changeRole(user)}
                    >
                      {user.role === "admin" ? "Demote to standard" : "Promote to admin"}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Create administrator account</Title>
        <Text c="dimmed" size="sm">
          The new account will be created directly in the admin group.
        </Text>
        <form onSubmit={createAdmin}>
          <Stack maw={480} gap="md">
            <TextInput
              label="Username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.currentTarget.value)}
              minLength={3}
              maxLength={32}
              pattern="[A-Za-z0-9_.-]+"
              required
            />
            <PasswordInput
              label="Temporary password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.currentTarget.value)}
              minLength={8}
              maxLength={128}
              required
            />
            <PasswordInput
              label="Confirm password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.currentTarget.value)}
              minLength={8}
              maxLength={128}
              required
            />
            <Group>
              <Button type="submit" loading={isSubmitting}>
                Create admin account
              </Button>
            </Group>
          </Stack>
        </form>
      </Stack>
    </Stack>
  );
}

type ManagedModel = {
  id: string;
  model_name: string;
  display_name: string;
  task: "llm" | "embedding" | "reranker";
  status: "queued" | "downloading" | "ready" | "failed" | "deleting";
  is_default: boolean;
  artifact_location: string | null;
  metadata: {
    device?: string;
    precision?: string;
    is_ovms?: boolean;
    requested_at?: string;
    logs?: string;
  };
};

function ModelManagementTab({ isAdmin }: { isAdmin: boolean }) {
  const [models, setModels] = useState<ManagedModel[]>([]);
  const [modelName, setModelName] = useState("");
  const [task, setTask] = useState("llm");
  const [device, setDevice] = useState("CPU");
  const [precision, setPrecision] = useState("int8");
  const [isOvms, setIsOvms] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [selectedFailure, setSelectedFailure] = useState<ManagedModel | null>(null);
  const [selectedRemoval, setSelectedRemoval] = useState<ManagedModel | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);
  const [dismissedNotifications, setDismissedNotifications] = useState<string[]>([]);

  const loadModels = useCallback(async () => {
    try {
      const response = await client.get<{ models: ManagedModel[] }>(
        SETTINGS_MODELS_URL,
      );
      setModels(response.data.models);
      setError("");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : "Could not load models. Check that the model download service is available.",
        );
      } else {
        setError("Could not load models. Check that the model download service is available.");
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadModels();
    const timer = window.setInterval(() => void loadModels(), 4000);
    return () => window.clearInterval(timer);
  }, [loadModels]);

  const submitModel = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    setIsSubmitting(true);
    try {
      await client.post(SETTINGS_MODELS_URL, {
        model_name: modelName.trim(),
        task,
        device,
        precision,
        is_ovms: isOvms,
      });
      setSuccess(`A request to add ${modelName.trim()} was submitted.`);
      setModelName("");
      await loadModels();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : "Could not submit the model request. Please try again.",
        );
      } else {
        setError("Could not submit the model request. Please try again.");
      }
      await loadModels();
    } finally {
      setIsSubmitting(false);
    }
  };

  const makeDefault = async (model: ManagedModel) => {
    setError("");
    setSuccess("");
    try {
      await client.put(`${SETTINGS_MODELS_URL}/default`, { model_id: model.id });
      setSuccess(`${model.display_name} is now the default ${model.task} model.`);
      await loadModels();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(typeof detail === "string" ? detail : "Could not update the default model.");
      } else {
        setError("Could not update the default model.");
      }
    }
  };

  const removeModel = async () => {
    if (!selectedRemoval) {
      return;
    }
    setError("");
    setSuccess("");
    setIsRemoving(true);
    try {
      await client.delete(SETTINGS_MODELS_URL, {
        data: { model_id: selectedRemoval.id },
      });
      setSuccess(`${selectedRemoval.display_name} was removed from the server.`);
      setSelectedRemoval(null);
      await loadModels();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = requestError.response?.data?.detail;
        setError(typeof detail === "string" ? detail : "Could not remove the model.");
      } else {
        setError("Could not remove the model.");
      }
    } finally {
      setIsRemoving(false);
    }
  };

  const notifications = models.filter(
    (model) =>
      model.metadata.requested_at &&
      !dismissedNotifications.includes(model.id) &&
      (model.status === "ready" || model.status === "failed" || model.status === "downloading"),
  );
  const modelTable = (title: string, rows: ManagedModel[]) => (
    <Stack gap="xs">
      <Title order={4}>{title}</Title>
      {rows.length === 0 ? (
        <Text c="dimmed" size="sm">No models found.</Text>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table
            striped
            stripedColor="#111a3b"
            highlightOnHover
            highlightOnHoverColor="#1c2b5b"
            withTableBorder
            withColumnBorders
            borderColor="#536487"
          >
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Model</Table.Th>
                <Table.Th>Device</Table.Th>
                <Table.Th>Precision</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Default</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((model) => (
                <Table.Tr key={model.id}>
                  <Table.Td>
                    <Text fw={500}>{model.display_name}</Text>
                    <Text size="xs" c="dimmed">{model.model_name}</Text>
                  </Table.Td>
                  <Table.Td>{model.metadata.device ?? "—"}</Table.Td>
                  <Table.Td>{model.metadata.precision ?? "—"}</Table.Td>
                  <Table.Td>
                    <Badge color={
                      model.status === "ready" ? "green" :
                        model.status === "failed" ? "red" : "blue"
                    }>
                      {model.status}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{model.is_default ? <Badge>Default</Badge> : "—"}</Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      {model.status === "ready" && !model.is_default && (
                        <Button size="xs" variant="light" onClick={() => void makeDefault(model)}>
                          Set default
                        </Button>
                      )}
                      {isAdmin && model.artifact_location && (
                        <Button
                          size="xs"
                          variant="light"
                          color="red"
                          disabled={model.status !== "ready" || model.is_default}
                          onClick={() => setSelectedRemoval(model)}
                        >
                          {model.is_default ? "Change default first" : "Remove"}
                        </Button>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );

  return (
    <Stack gap="xl">
      <Stack gap="xs">
        <Title order={3}>Model notifications</Title>
        {notifications.length === 0 ? (
          <Text c="dimmed" size="sm">No recent model requests.</Text>
        ) : notifications.map((model) => (
          <Alert
            key={model.id}
            color={model.status === "failed" ? "red" : model.status === "ready" ? "green" : "blue"}
            title={
              model.status === "failed"
                ? `Model request failed: ${model.display_name}`
                : model.status === "ready"
                  ? `Model available: ${model.display_name}`
                  : `Model request in progress: ${model.display_name}`
            }
            withCloseButton
            onClose={() => setDismissedNotifications((current) => [...current, model.id])}
          >
            {model.status === "failed" ? (
              <Button
                size="xs"
                variant="subtle"
                color="red"
                onClick={() => setSelectedFailure(model)}
              >
                View failure log
              </Button>
            ) : model.status === "ready" ? (
              <Text size="sm">The model is ready to use.</Text>
            ) : (
              <Text size="sm">This page checks for updates automatically.</Text>
            )}
          </Alert>
        ))}
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Available models</Title>
        <Text c="dimmed" size="sm">
          Models are shared across users and listed from the OVMS model directory.
          Changing the embedding default may require re-indexing existing documents.
        </Text>
        {error && <Alert color="red">{error}</Alert>}
        {success && <Alert color="green">{success}</Alert>}
        {isLoading ? (
          <Text size="sm">Loading model catalog…</Text>
        ) : (
          <Stack gap="lg">
            {modelTable("LLM", models.filter((model) => model.task === "llm"))}
            {modelTable(
              "Reranker / Embedding",
              models.filter((model) => model.task === "reranker" || model.task === "embedding"),
            )}
          </Stack>
        )}
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Add a Hugging Face model</Title>
        <Text c="dimmed" size="sm">
          The model download service will download or convert the repository using the selected settings.
        </Text>
        <form onSubmit={submitModel}>
          <Stack maw={560} gap="md">
            <TextInput
              label="Hugging Face model name"
              placeholder="deepseek-ai/dspark_qwen3_4b_block7"
              value={modelName}
              onChange={(event) => setModelName(event.currentTarget.value)}
              maxLength={256}
              required
            />
            <Select
              label="Model task"
              data={[
                { value: "llm", label: "LLM" },
                { value: "embedding", label: "Embedding" },
                { value: "reranker", label: "Reranker" },
              ]}
              value={task}
              onChange={(value) => value && setTask(value)}
              allowDeselect={false}
            />
            <Group grow>
              <Select
                label="Device"
                data={["CPU", "GPU", "NPU"]}
                value={device}
                onChange={(value) => value && setDevice(value)}
                allowDeselect={false}
              />
              <Select
                label="Precision"
                data={["int4", "int8", "fp16", "fp32"]}
                value={precision}
                onChange={(value) => value && setPrecision(value)}
                allowDeselect={false}
              />
            </Group>
            <Checkbox
              label="Convert model for OVMS (is_ovms)"
              checked={isOvms}
              onChange={(event) => setIsOvms(event.currentTarget.checked)}
            />
            <Group>
              <Button type="submit" loading={isSubmitting} disabled={isLoading}>
                Request model
              </Button>
            </Group>
          </Stack>
        </form>
      </Stack>

      <Modal
        opened={selectedFailure !== null}
        onClose={() => setSelectedFailure(null)}
        title={`Failure details: ${selectedFailure?.display_name ?? ""}`}
        size="lg"
      >
        <Stack>
          <Text size="sm">Download/conversion log</Text>
          <ScrollArea h={360} type="auto" offsetScrollbars>
            <Code block style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {selectedFailure?.metadata.logs || "No detailed log was captured."}
            </Code>
          </ScrollArea>
        </Stack>
      </Modal>
      <Modal
        opened={selectedRemoval !== null}
        onClose={() => setSelectedRemoval(null)}
        title="Remove model from server?"
      >
        <Stack>
          <Text size="sm">
            This permanently deletes the installed files for{" "}
            <strong>{selectedRemoval?.model_name}</strong> and removes its catalog entry.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setSelectedRemoval(null)}>
              Cancel
            </Button>
            <Button color="red" loading={isRemoving} onClick={() => void removeModel()}>
              Remove model
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

export function SettingsPage({
  onBack,
  isAdmin = false,
  currentUserId,
}: SettingsPageProps) {
  const settingsTabs = [
    {
      value: "password",
      label: "Password",
      panel: <ChangePasswordTab />,
    },
    {
      value: "huggingface",
      label: "Hugging Face",
      panel: <HuggingFaceTokenTab />,
    },
    {
      value: "models",
      label: "Models",
      panel: <ModelManagementTab isAdmin={isAdmin} />,
    },
    ...(isAdmin
      ? [{
          value: "admin",
          label: "Admin",
          panel: <AdminManagementTab currentUserId={currentUserId} />,
        }]
      : []),
  ];
  const [activeTab, setActiveTab] = useState<string | null>("password");

  return (
    <main
      className={classes.settingsPage}
      style={{ width: "100%", overflowY: "auto", padding: "32px" }}
    >
      <Stack maw={900} mx="auto" gap="xl">
        <Group justify="space-between">
          <Title order={2}>Settings</Title>
          <Button variant="subtle" onClick={onBack}>
            Back to chat
          </Button>
        </Group>
        <Tabs value={activeTab} onChange={setActiveTab}>
          <Tabs.List>
            {settingsTabs.map((tab) => (
              <Tabs.Tab key={tab.value} value={tab.value}>
                {tab.label}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
        <div style={{ paddingTop: "var(--mantine-spacing-xl)" }}>
          {settingsTabs.find((tab) => tab.value === activeTab)?.panel}
        </div>
      </Stack>
    </main>
  );
}
