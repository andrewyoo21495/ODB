import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Select,
  Space,
  Switch,
  Tag,
} from "antd";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useJob } from "../JobContext";
import PcbCanvas, { type Overlay } from "../components/PcbCanvas";
import type { LayerGeometry, PolyMeta, TaskOut } from "../types";

const PALETTE = ["#00c2c2", "#ff7875", "#95de64", "#ffc53d", "#b37feb", "#69b1ff", "#ff9c6e", "#5cdbd3"];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function labelOf(key: string): string {
  if (key.startsWith("L:")) return key.slice(2);
  if (key.startsWith("C:")) return `Comp ${key.slice(2)}`;
  if (key.startsWith("N:")) {
    const parts = key.split(":");
    return `Net ${parts[2]} @ ${parts[1]}`;
  }
  return key;
}

export default function Viewer() {
  const { jobId } = useJob();
  const { message } = AntdApp.useApp();
  const [overlays, setOverlays] = useState<Overlay[]>([]);
  const [loading, setLoading] = useState(0);
  const [fitToken, setFitToken] = useState(0);
  const [showLabels, setShowLabels] = useState(false);
  const [picked, setPicked] = useState<PolyMeta | null>(null);
  const [netLayer, setNetLayer] = useState<string | null>(null);
  const [netName, setNetName] = useState<string | null>(null);

  const layers = useQuery({
    queryKey: ["layers", jobId],
    queryFn: () => api.getLayers(jobId as string),
    enabled: !!jobId,
  });
  const nets = useQuery({
    queryKey: ["nets", jobId, netLayer],
    queryFn: () => api.getNets(jobId as string, netLayer as string),
    enabled: !!jobId && !!netLayer,
  });

  async function loadGeom(start: () => Promise<TaskOut>): Promise<LayerGeometry> {
    const t0 = await start();
    let t = t0;
    for (let i = 0; i < 150 && t.status !== "done" && t.status !== "error"; i++) {
      await sleep(700);
      t = await api.getTask(t0.task_id);
    }
    if (t.status !== "done") throw new Error(t.error || "timeout");
    const geometry = (t.result as { geometry: string }).geometry;
    return api.fetchGeometry(t0.task_id, geometry);
  }

  async function addOverlay(key: string, color: string, start: () => Promise<TaskOut>) {
    if (overlays.some((o) => o.key === key)) {
      setOverlays((prev) => prev.map((o) => (o.key === key ? { ...o, visible: true } : o)));
      return;
    }
    setLoading((n) => n + 1);
    try {
      const geom = await loadGeom(start);
      setOverlays((prev) => (prev.some((o) => o.key === key) ? prev : [...prev, { key, color, visible: true, geom }]));
      setFitToken((t) => t + 1);
    } catch (e) {
      message.error(String(e));
    } finally {
      setLoading((n) => n - 1);
    }
  }

  const removeOverlay = (key: string) => setOverlays((prev) => prev.filter((o) => o.key !== key));
  const toggleVisible = (key: string) =>
    setOverlays((prev) => prev.map((o) => (o.key === key ? { ...o, visible: !o.visible } : o)));

  if (!jobId) {
    return <Alert type="info" showIcon message="대시보드에서 Job을 먼저 선택하세요." />;
  }

  const activeLayers = overlays.filter((o) => o.key.startsWith("L:")).map((o) => o.key.slice(2));
  const activeSides = (["top", "bottom"] as const).filter((s) => overlays.some((o) => o.key === `C:${s}`));

  const onLayersChange = (next: string[]) => {
    activeLayers.filter((n) => !next.includes(n)).forEach((n) => removeOverlay(`L:${n}`));
    next
      .filter((n) => !activeLayers.includes(n))
      .forEach((n, i) =>
        addOverlay(`L:${n}`, PALETTE[(overlays.length + i) % PALETTE.length], () => api.runViewer(jobId, n)),
      );
  };

  const onSidesChange = (list: string[]) => {
    (["top", "bottom"] as const).forEach((s) => {
      const key = `C:${s}`;
      const want = list.includes(s);
      const has = overlays.some((o) => o.key === key);
      if (want && !has) addOverlay(key, "#8c8c8c", () => api.runViewerComponent(jobId, s));
      if (!want && has) removeOverlay(key);
    });
  };

  const layerOptions = (layers.data ?? []).map((l) => ({ label: `${l.name} (${l.type})`, value: l.name }));
  const signalOptions = (layers.data ?? [])
    .filter((l) => l.type === "SIGNAL")
    .map((l) => ({ label: l.name, value: l.name }));

  return (
    <Card title={`ODB Viewer — job ${jobId}`}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Space wrap align="start">
          <div>
            <div style={{ fontSize: 12, color: "#888" }}>레이어 (다중)</div>
            <Select
              mode="multiple"
              style={{ width: 360 }}
              placeholder="레이어 추가"
              loading={layers.isLoading}
              value={activeLayers}
              onChange={onLayersChange}
              showSearch
              optionFilterProp="label"
              maxTagCount="responsive"
              options={layerOptions}
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: "#888" }}>부품</div>
            <Checkbox.Group
              value={activeSides}
              onChange={(v) => onSidesChange(v as string[])}
              options={[
                { label: "Top", value: "top" },
                { label: "Bottom", value: "bottom" },
              ]}
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: "#888" }}>Net 하이라이트</div>
            <Space.Compact>
              <Select
                style={{ width: 150 }}
                placeholder="Signal layer"
                value={netLayer}
                onChange={(v) => { setNetLayer(v); setNetName(null); }}
                showSearch
                optionFilterProp="label"
                options={signalOptions}
              />
              <Select
                style={{ width: 170 }}
                placeholder="net"
                loading={nets.isLoading}
                value={netName}
                onChange={setNetName}
                disabled={!netLayer}
                showSearch
                optionFilterProp="label"
                options={(nets.data ?? []).map((n) => ({ label: n, value: n }))}
              />
              <Button
                disabled={!netLayer || !netName}
                onClick={() =>
                  addOverlay(`N:${netLayer}:${netName}`, "#ff4d4f", () =>
                    api.runViewerNet(jobId, netLayer as string, netName as string),
                  )
                }
              >
                추가
              </Button>
            </Space.Compact>
          </div>
        </Space>

        <Space wrap>
          <Button onClick={() => setFitToken((t) => t + 1)}>Fit</Button>
          <span>
            <Switch size="small" checked={showLabels} onChange={setShowLabels} /> refdes 라벨(확대 시)
          </span>
          {loading > 0 && <Tag color="processing">로딩 중… ({loading})</Tag>}
        </Space>

        {/* Active overlays */}
        {overlays.length > 0 && (
          <Space wrap>
            {overlays.map((o) => (
              <Tag
                key={o.key}
                closable
                onClose={() => removeOverlay(o.key)}
                onClick={() => toggleVisible(o.key)}
                style={{ cursor: "pointer", opacity: o.visible ? 1 : 0.4, borderLeft: `6px solid ${o.color}` }}
              >
                {labelOf(o.key)} {o.visible ? "" : "(숨김)"}
              </Tag>
            ))}
          </Space>
        )}

        {overlays.length === 0 ? (
          <Alert type="info" showIcon message="레이어/부품/넷을 추가하면 캔버스에 표시됩니다." />
        ) : (
          <PcbCanvas overlays={overlays} showLabels={showLabels} fitToken={fitToken} onPick={setPicked} />
        )}

        {picked && (
          <Descriptions size="small" bordered column={2} title="선택한 부품" style={{ maxWidth: 700 }}>
            <Descriptions.Item label="RefDes">{picked.refdes}</Descriptions.Item>
            <Descriptions.Item label="Category">{picked.category}</Descriptions.Item>
            <Descriptions.Item label="Part" span={2}>{picked.part}</Descriptions.Item>
          </Descriptions>
        )}
      </Space>
    </Card>
  );
}
