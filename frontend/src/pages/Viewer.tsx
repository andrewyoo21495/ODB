import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Segmented,
  Select,
  Space,
  Switch,
  Tag,
} from "antd";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useJob } from "../JobContext";
import { useJobName } from "../hooks/useJobName";
import PcbCanvas, { type Overlay } from "../components/PcbCanvas";
import type { LayerGeometry, PolyMeta, TaskOut } from "../types";

const PALETTE = ["#00c2c2", "#ff7875", "#95de64", "#ffc53d", "#b37feb", "#69b1ff", "#ff9c6e", "#5cdbd3"];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function labelOf(key: string): string {
  if (key.startsWith("L:")) return key.slice(2);
  if (key.startsWith("C:")) return `부품 ${key.slice(2)}`;
  if (key.startsWith("N:")) {
    const parts = key.split(":");
    return `Net ${parts[2]} @ ${parts[1]}`;
  }
  return key;
}

export default function Viewer() {
  const { jobId } = useJob();
  const jobName = useJobName(jobId);
  const { message } = AntdApp.useApp();
  const [overlays, setOverlays] = useState<Overlay[]>([]);
  const [loading, setLoading] = useState(0);
  const [fitToken, setFitToken] = useState(0);
  const [showLabels, setShowLabels] = useState(false);
  const [picked, setPicked] = useState<PolyMeta | null>(null);
  // Component-view role toggles (match legacy view-comp: pins+outline on, via off).
  const [showPads, setShowPads] = useState(true);
  const [showOutlines, setShowOutlines] = useState(true);
  const [showVias, setShowVias] = useState(false);
  const [netLayer, setNetLayer] = useState<string | null>(null);
  const [netName, setNetName] = useState<string | null>(null);
  // Component selection (legacy view-comp UX): pick side -> list -> select -> show.
  const [compSide, setCompSide] = useState<"top" | "bottom" | "both">("top");
  const [compSelected, setCompSelected] = useState<string[]>([]);

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
  const components = useQuery({
    queryKey: ["components", jobId, compSide],
    queryFn: () => api.getComponents(jobId as string, compSide),
    enabled: !!jobId,
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
    // Insert a loading placeholder right away so the selection chip/checkbox
    // reflects the choice immediately (geometry fills in when it arrives).
    setOverlays((prev) =>
      prev.some((o) => o.key === key) ? prev : [...prev, { key, color, visible: true, loading: true }],
    );
    setLoading((n) => n + 1);
    try {
      const geom = await loadGeom(start);
      setOverlays((prev) => prev.map((o) => (o.key === key ? { ...o, geom, loading: false } : o)));
      setFitToken((t) => t + 1);
    } catch (e) {
      message.error(String(e));
      removeOverlay(key); // drop the failed placeholder
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
  const hasComp = overlays.some((o) => o.key.startsWith("C:"));

  const onLayersChange = (next: string[]) => {
    activeLayers.filter((n) => !next.includes(n)).forEach((n) => removeOverlay(`L:${n}`));
    next
      .filter((n) => !activeLayers.includes(n))
      .forEach((n, i) =>
        addOverlay(`L:${n}`, PALETTE[(overlays.length + i) % PALETTE.length], () => api.runViewer(jobId, n)),
      );
  };

  // Render the selected components (empty selection = all) on the chosen side(s).
  // Only one component overlay is kept at a time (legacy single-canvas behavior),
  // so each "표시" replaces the previous component geometry.
  const showComponents = async () => {
    const key = `C:${compSide}`;
    const refdes = compSelected.length ? compSelected : null;
    setOverlays((prev) => prev.filter((o) => !o.key.startsWith("C:")));
    setOverlays((prev) =>
      prev.some((o) => o.key === key) ? prev : [...prev, { key, color: "#8c8c8c", visible: true, loading: true }],
    );
    setLoading((n) => n + 1);
    try {
      const geom = await loadGeom(() => api.runViewerComponent(jobId, compSide, refdes));
      setOverlays((prev) => prev.map((o) => (o.key === key ? { ...o, geom, loading: false } : o)));
      setFitToken((t) => t + 1);
    } catch (e) {
      message.error(String(e));
      setOverlays((prev) => prev.filter((o) => o.key !== key));
    } finally {
      setLoading((n) => n - 1);
    }
  };

  const layerOptions = (layers.data ?? []).map((l) => ({ label: `${l.name} (${l.type})`, value: l.name }));
  const signalOptions = (layers.data ?? [])
    .filter((l) => l.type === "SIGNAL")
    .map((l) => ({ label: l.name, value: l.name }));

  return (
    <Card title={`ODB 뷰어 — ${jobName || jobId}`}>
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
            <div style={{ fontSize: 12, color: "#888" }}>부품 (면 → 선택 → 표시)</div>
            <Space direction="vertical" size={4}>
              <Segmented
                size="small"
                value={compSide}
                onChange={(v) => {
                  setCompSide(v as "top" | "bottom" | "both");
                  setCompSelected([]);
                }}
                options={[
                  { label: "Top", value: "top" },
                  { label: "Bottom", value: "bottom" },
                  { label: "Both", value: "both" },
                ]}
              />
              <Space.Compact>
                <Select
                  mode="multiple"
                  style={{ width: 300 }}
                  placeholder="부품 선택 (비우면 전체)"
                  loading={components.isLoading}
                  value={compSelected}
                  onChange={setCompSelected}
                  showSearch
                  optionFilterProp="label"
                  maxTagCount="responsive"
                  options={(components.data ?? []).map((c) => ({
                    label: `${c.refdes} — ${c.part} (${c.category})`,
                    value: c.refdes,
                  }))}
                />
                <Button type="primary" onClick={showComponents}>
                  표시
                </Button>
              </Space.Compact>
              <Space size={4} wrap>
                <Button
                  size="small"
                  onClick={() =>
                    setCompSelected([...new Set((components.data ?? []).map((c) => c.refdes))])
                  }
                >
                  전체 선택
                </Button>
                <Button size="small" onClick={() => setCompSelected([])}>
                  선택 해제
                </Button>
                <span style={{ fontSize: 12, color: "#888" }}>
                  {compSelected.length ? `${compSelected.length}개 선택` : "전체"}
                </span>
              </Space>
            </Space>
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

        {hasComp && (
          <Space wrap>
            <span style={{ fontSize: 12, color: "#888" }}>부품 표시:</span>
            <Checkbox checked={showPads} onChange={(e) => setShowPads(e.target.checked)}>
              패드(핀)
            </Checkbox>
            <Checkbox checked={showOutlines} onChange={(e) => setShowOutlines(e.target.checked)}>
              외곽선
            </Checkbox>
            <Checkbox checked={showVias} onChange={(e) => setShowVias(e.target.checked)}>
              VIA
            </Checkbox>
          </Space>
        )}

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
                {labelOf(o.key)} {o.loading ? "(로딩중…)" : o.visible ? "" : "(숨김)"}
              </Tag>
            ))}
          </Space>
        )}

        {overlays.length === 0 ? (
          <Alert type="info" showIcon message="레이어/부품/넷을 추가하면 캔버스에 표시됩니다." />
        ) : (
          <PcbCanvas
            overlays={overlays}
            showLabels={showLabels}
            fitToken={fitToken}
            onPick={setPicked}
            showPads={showPads}
            showOutlines={showOutlines}
            showVias={showVias}
          />
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
