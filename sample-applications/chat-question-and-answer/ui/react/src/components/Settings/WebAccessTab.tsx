import { FormEvent, useCallback, useEffect, useState } from "react";
import { Alert, Button, Group, Select, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import axios from "axios";
import { WEB_ACCESS_URL } from "../../config";
import client from "../../utils/client";

type WebRule = {
  kind: "url" | "phrase";
  effect: "allow" | "deny";
  value: string;
};

export function WebAccessTab() {
  const [rules, setRules] = useState<WebRule[]>([]);
  const [kind, setKind] = useState<WebRule["kind"]>("url");
  const [effect, setEffect] = useState<WebRule["effect"]>("allow");
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const response = await client.get<{ rules: WebRule[] }>(WEB_ACCESS_URL);
      setRules(response.data.rules);
      setLoaded(true);
    } catch {
      setLoaded(false);
      setError("Could not load web access rules. Please retry.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async (updated: WebRule[]) => {
    setSaving(true);
    setError("");
    try {
      const response = await client.put<{ rules: WebRule[] }>(WEB_ACCESS_URL, { rules: updated });
      setRules(response.data.rules);
      setValue("");
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError) ? requestError.response?.data?.detail : undefined;
      setError(typeof detail === "string" ? detail : "Could not save web access rules. Please retry.");
    } finally {
      setSaving(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void save([...rules, { kind, effect, value }]);
  };

  return (
    <Stack gap="md">
      <Title order={3}>Web access</Title>
      <Text size="sm" c="dimmed">
        Rules apply only to your account. Web access is off unless enabled for a chat message.
        Add exact public HTTPS page URLs and search phrases. A question must contain an allowed
        phrase or URL; denied phrases and URLs take precedence. Search results are fetched only
        when their exact URLs are allowed. Search phrases are sent to Bing: never add sensitive information.
      </Text>
      {error && <Alert color="red">{error}{loading ? null : <Button size="xs" variant="subtle" onClick={() => void load()}>Reload rules</Button>}</Alert>}
      {loading ? <Text>Loading web access rules...</Text> : loaded ? (
        <>
          {rules.length === 0 ? <Text size="sm">No rules configured; web access is blocked.</Text> : (
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Action</Table.Th><Table.Th>Type</Table.Th><Table.Th>Value</Table.Th><Table.Th /></Table.Tr></Table.Thead>
              <Table.Tbody>{rules.map((rule, index) => (
                <Table.Tr key={`${rule.effect}-${rule.kind}-${rule.value}`}>
                  <Table.Td>{rule.effect}</Table.Td><Table.Td>{rule.kind}</Table.Td><Table.Td>{rule.value}</Table.Td>
                  <Table.Td><Button size="xs" variant="subtle" disabled={saving} onClick={() => void save(rules.filter((_, i) => i !== index))} aria-label={`Remove ${rule.value}`}>Remove</Button></Table.Td>
                </Table.Tr>
              ))}</Table.Tbody>
            </Table>
          )}
          <form onSubmit={submit}>
            <Stack maw={600}>
              <Group grow>
                <Select label="Action" value={effect} data={[{ value: "allow", label: "Allow" }, { value: "deny", label: "Deny" }]} allowDeselect={false} onChange={(v) => { if (v === "allow" || v === "deny") setEffect(v); }} />
                <Select label="Rule type" value={kind} data={[{ value: "url", label: "Page URL" }, { value: "phrase", label: "Search phrase" }]} allowDeselect={false} onChange={(v) => { if (v === "url" || v === "phrase") setKind(v); }} />
              </Group>
              <TextInput label={kind === "url" ? "HTTPS page URL" : "Search phrase"} value={value} onChange={(event) => setValue(event.currentTarget.value)} maxLength={kind === "url" ? 2048 : 160} required />
              <Group><Button type="submit" loading={saving}>Add rule</Button></Group>
            </Stack>
          </form>
        </>
      ) : null}
    </Stack>
  );
}
