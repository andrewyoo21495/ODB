import { Card, Space, Table, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ActivityEntry, ActivityUser } from "../types";

export default function Activity() {
  const activity = useQuery({
    queryKey: ["activity"],
    queryFn: () => api.getActivity(300),
    refetchInterval: 5000,
  });

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
