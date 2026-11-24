import { FormEvent, useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Group, Modal, Select, Stack, Table, Text, Textarea, TextInput, Title } from "@mantine/core";
import axios from "axios";
import { MODELS_URL, SYSTEM_PROMPTS_URL } from "../../config";
import client from "../../utils/client";

type Prompt = { id: string; name: string; content: string; is_default: boolean };
type Assignment = { scope: "model" | "family"; target: string; prompt_id: string };
type Model = { model_name: string; display_name: string; task: string };

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && typeof error.response?.data?.detail === "string") {
    return error.response.data.detail;
  }
  return "Could not update system prompt settings. Please try again.";
}

export function SystemPromptsTab() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [scope, setScope] = useState<"model" | "family">("family");
  const [target, setTarget] = useState("");
  const [promptId, setPromptId] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Prompt | null>(null);

  const load = useCallback(async () => {
    const [settings, catalog] = await Promise.all([
      client.get<{ prompts: Prompt[]; assignments: Assignment[] }>(SYSTEM_PROMPTS_URL),
      client.get<{ models: Model[] }>(MODELS_URL),
    ]);
    setPrompts(settings.data.prompts);
    setAssignments(settings.data.assignments);
    setModels(catalog.data.models.filter((model) => model.task === "llm"));
  }, []);

  useEffect(() => {
    void load().catch((requestError: unknown) => setError(errorMessage(requestError)))
      .finally(() => setLoading(false));
  }, [load]);

  const run = async (action: () => Promise<void>, message: string) => {
    setError("");
    setSuccess("");
    setBusy(true);
    try {
      await action();
      await load();
      setSuccess(message);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run(async () => {
      if (editing) {
        await client.put(`${SYSTEM_PROMPTS_URL}/${encodeURIComponent(editing)}`, { name, content });
      } else {
        await client.post(SYSTEM_PROMPTS_URL, { name, content });
      }
      setEditing(null);
      setName("");
      setContent("");
    }, "System prompt saved.");
  };

  const assign = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!promptId) {
      setError("Choose a system prompt.");
      return;
    }
    void run(async () => {
      await client.put(`${SYSTEM_PROMPTS_URL}/assignments`, { scope, target, prompt_id: promptId });
      setTarget("");
    }, "Assignment saved.");
  };

  return (
    <Stack gap="xl">
      <Stack gap="xs">
        <Title order={3}>System prompts</Title>
        <Text size="sm" c="dimmed">
          These instructions are shared by all users and sent as a system message.
          Exact model assignments take precedence over family matches, then the default.
          Family matches are case-insensitive substrings; the longest match wins.
        </Text>
        {error && <Alert color="red">{error}</Alert>}
        {success && <Alert color="green">{success}</Alert>}
        {loading ? <Text>Loading system prompts…</Text> : (
          <Table.ScrollContainer minWidth={600}>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Prompt</Table.Th><Table.Th>Default</Table.Th><Table.Th>Actions</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {prompts.map((prompt) => (
                  <Table.Tr key={prompt.id}>
                    <Table.Td>{prompt.name}</Table.Td>
                    <Table.Td>{prompt.is_default ? <Badge>Default</Badge> : "—"}</Table.Td>
                    <Table.Td>
                      <Group gap="xs">
                        <Button size="xs" variant="light" disabled={busy} onClick={() => {
                          setEditing(prompt.id); setName(prompt.name); setContent(prompt.content);
                        }}>Edit</Button>
                        {!prompt.is_default && <>
                          <Button size="xs" variant="light" disabled={busy} onClick={() => void run(
                            async () => { await client.put(`${SYSTEM_PROMPTS_URL}/${encodeURIComponent(prompt.id)}/default`); },
                            "Default system prompt updated.",
                          )}>Set default</Button>
                          <Button size="xs" color="red" variant="light" disabled={busy} onClick={() => setRemoving(prompt)}>Delete</Button>
                        </>}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>

      <form onSubmit={save}>
        <Stack maw={700}>
          <Title order={4}>{editing ? "Edit system prompt" : "Add system prompt"}</Title>
          <TextInput label="Prompt name" value={name} onChange={(event) => setName(event.currentTarget.value)} maxLength={128} required />
          <Textarea label="System instructions" value={content} onChange={(event) => setContent(event.currentTarget.value)} minRows={6} maxLength={20000} required />
          <Group>
            <Button type="submit" loading={busy} disabled={loading}>Save prompt</Button>
            {editing && <Button variant="default" onClick={() => { setEditing(null); setName(""); setContent(""); }}>Cancel editing</Button>}
          </Group>
        </Stack>
      </form>

      <Stack gap="sm">
        <Title order={4}>Model and family assignments</Title>
        {assignments.length === 0 ? <Text size="sm">No assignments.</Text> : (
          <Table.ScrollContainer minWidth={550}>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Scope</Table.Th><Table.Th>Target</Table.Th><Table.Th>Prompt</Table.Th><Table.Th /></Table.Tr></Table.Thead>
              <Table.Tbody>{assignments.map((assignment) => (
                <Table.Tr key={`${assignment.scope}:${assignment.target}`}>
                  <Table.Td>{assignment.scope}</Table.Td><Table.Td>{assignment.target}</Table.Td>
                  <Table.Td>{prompts.find((prompt) => prompt.id === assignment.prompt_id)?.name ?? assignment.prompt_id}</Table.Td>
                  <Table.Td><Button size="xs" variant="subtle" color="red" disabled={busy} onClick={() => void run(
                    async () => { await client.delete(`${SYSTEM_PROMPTS_URL}/assignments`, { data: { scope: assignment.scope, target: assignment.target } }); },
                    "Assignment removed.",
                  )}>Remove</Button></Table.Td>
                </Table.Tr>
              ))}</Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        <form onSubmit={assign}>
          <Stack maw={560}>
            <Select label="Assignment scope" value={scope} data={[
              { value: "family", label: "Model family" },
              { value: "model", label: "Exact model" },
            ]} allowDeselect={false} onChange={(value) => {
              if (value === "family" || value === "model") { setScope(value); setTarget(""); }
            }} />
            {scope === "family" ? (
              <TextInput label="Family match" description="Case-insensitive substring of the model name, for example qwen." value={target} onChange={(event) => setTarget(event.currentTarget.value)} maxLength={512} required />
            ) : (
              <Select label="Model" value={target || null} data={Array.from(new Map(models.map((model) => [
                model.model_name, { value: model.model_name, label: `${model.display_name} (${model.model_name})` },
              ])).values())} onChange={(value) => setTarget(value ?? "")} searchable required />
            )}
            <Select label="Assigned system prompt" value={promptId} data={prompts.map((prompt) => ({ value: prompt.id, label: prompt.name }))} onChange={setPromptId} required />
            <Group><Button type="submit" loading={busy} disabled={loading || !target || !promptId}>Save assignment</Button></Group>
          </Stack>
        </form>
      </Stack>

      <Modal opened={removing !== null} onClose={() => setRemoving(null)} title="Delete system prompt?">
        <Stack>
          <Text>Delete {removing?.name}? Its model and family assignments will also be removed.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRemoving(null)}>Cancel</Button>
            <Button color="red" loading={busy} onClick={() => {
              if (removing) {
                void run(async () => {
                  await client.delete(`${SYSTEM_PROMPTS_URL}/${encodeURIComponent(removing.id)}`);
                  if (editing === removing.id) {
                    setEditing(null);
                    setName("");
                    setContent("");
                  }
                  if (promptId === removing.id) {
                    setPromptId(null);
                  }
                  setRemoving(null);
                }, "System prompt deleted.");
              }
            }}>Delete prompt</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
