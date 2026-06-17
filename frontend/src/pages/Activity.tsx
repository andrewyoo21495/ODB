import { useState } from "react";
import { Alert, Button, Card, Form, Input, Space, Table, Tag } from "antd";
import { LockOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ActivityEntry, ActivityUser } from "../types";

// Keep the verified password for the rest of the browser session so navigating
// away and back doesn't re-prompt; cleared when the browser/tab closes.
const PW_KEY = "odbhub.managerpw";

export default function Activity() {
  const [pw, setPw] = useState<string>(() => sessionStorage.getItem(PW_KEY) || "");
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [verifying, setVerifying] = useState(false);

  const verify = async () => {
    setVerifying(true);
    setError("");
    try {
      await api.getActivity(1, input); // 401 throws if wrong
      sessionStorage.setItem(PW_KEY, input);
      setPw(input);
    } catch {
      setError("비밀번호가 올바르지 않습니다.");
    } finally {
      setVerifying(false);
    }
  };

  if (!pw) {
    return (
      <Card title="사용자 현황 — 비밀번호 입력" style={{ maxWidth: 420, margin: "48px auto" }}>
        <Form layout="vertical" onFinish={verify}>
          <Form.Item label="이 페이지는 관리자 전용입니다.">
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="비밀번호"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              autoFocus
            />
          </Form.Item>
          {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
          <Button type="primary" htmlType="submit" block loading={verifying} disabled={!input}>
            확인
          </Button>
        </Form>
      </Card>
    );
  }

  return <ActivityContent pw={pw} onForbidden={() => {
    sessionStorage.removeItem(PW_KEY);
    setPw("");
  }} />;
}

function ActivityContent({ pw, onForbidden }: { pw: string; onForbidden: () => void }) {
  const activity = useQuery({
    queryKey: ["activity", pw],
    queryFn: () => api.getActivity(300, pw),
    refetchInterval: 5000,
    retry: false,
  });

  // Password changed/revoked on the server -> drop back to the prompt.
  if (activity.isError) onForbidden();

  const users = activity.data?.users ?? [];
  const recent = activity.data?.recent ?? [];

  const userColumns = [
    { title: "사용자", dataIndex: "user", render: (u: string) => <Tag color="blue">{u}</Tag> },
    {
      title: "IP",
      dataIndex: "ips",
      render: (ips: string[]) => (
        <Space wrap>{ips.map((ip) => <Tag key={ip}>{ip}</Tag>)}</Space>
      ),
    },
    { title: "요청 수", dataIndex: "count" },
    {
      title: "마지막 접속",
      dataIndex: "last_seen",
      render: (t: string) => (t ? new Date(t).toLocaleString() : "-"),
    },
  ];

  const recentColumns = [
    {
      title: "시각",
      dataIndex: "ts",
      render: (t: string) => (t ? new Date(t).toLocaleString() : "-"),
    },
    { title: "사용자", dataIndex: "user", render: (u: string) => <Tag color="blue">{u}</Tag> },
    { title: "IP", dataIndex: "ip" },
    { title: "메서드", dataIndex: "method", render: (m: string) => <Tag>{m}</Tag> },
    { title: "경로", dataIndex: "path" },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="large">
      <Card title="사용자 현황 — 접속 요약" loading={activity.isLoading}>
        <Table<ActivityUser>
          rowKey="user"
          size="small"
          dataSource={users}
          columns={userColumns}
          pagination={false}
        />
      </Card>

      <Card title="최근 활동 로그">
        <Table<ActivityEntry>
          rowKey={(_r, i) => String(i)}
          size="small"
          dataSource={recent}
          columns={recentColumns}
          pagination={{ pageSize: 20 }}
        />
      </Card>
    </Space>
  );
}
