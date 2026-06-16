import { useEffect, useRef } from "react";
import type { LayerGeometry, PolyMeta, Ring } from "../types";

const W = 940;
const H = 640;
const LABEL_MIN_SCALE = 6; // show refdes labels only when zoomed in past this

export interface Overlay {
  key: string;
  color: string;
  visible: boolean;
  geom: LayerGeometry;
}

interface Props {
  overlays: Overlay[];
  showLabels?: boolean;
  fitToken?: number; // bump to re-fit the view
  onPick?: (meta: PolyMeta | null) => void;
}

type Pt = [number, number];

function pointInRing(x: number, y: number, ring: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const hit = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (hit) inside = !inside;
  }
  return inside;
}

export default function PcbCanvas({ overlays, showLabels = false, fitToken = 0, onPick }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const coordRef = useRef<HTMLSpanElement>(null);
  const view = useRef({ scale: 1, tx: 0, ty: 0 });
  const drag = useRef<{ sx: number; sy: number; tx: number; ty: number; moved: boolean } | null>(null);
  // Latest props for use inside stable event handlers.
  const ov = useRef(overlays);
  ov.current = overlays;
  const labels = useRef(showLabels);
  labels.current = showLabels;

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;

    const visible = () => ov.current.filter((o) => o.visible && o.geom);

    const unionBounds = (): [number, number, number, number] => {
      const vs = visible();
      if (!vs.length) return [0, 0, 1, 1];
      let [minx, miny, maxx, maxy] = vs[0].geom.bounds;
      for (const o of vs) {
        const b = o.geom.bounds;
        minx = Math.min(minx, b[0]); miny = Math.min(miny, b[1]);
        maxx = Math.max(maxx, b[2]); maxy = Math.max(maxy, b[3]);
      }
      return [minx, miny, maxx, maxy];
    };

    const fit = () => {
      const [minx, miny, maxx, maxy] = unionBounds();
      const bw = maxx - minx || 1, bh = maxy - miny || 1;
      const s = 0.92 * Math.min(W / bw, H / bh);
      view.current = { scale: s, tx: (W - bw * s) / 2 - minx * s, ty: (H - bh * s) / 2 - miny * s };
    };

    const ring = (pts: Pt[], toX: (n: number) => number, toY: (n: number) => number) => {
      if (pts.length < 2) return;
      ctx.moveTo(toX(pts[0][0]), toY(pts[0][1]));
      for (let i = 1; i < pts.length; i++) ctx.lineTo(toX(pts[i][0]), toY(pts[i][1]));
      ctx.closePath();
    };

    const draw = () => {
      const { scale, tx, ty } = view.current;
      const toX = (x: number) => x * scale + tx;
      const toY = (y: number) => H - (y * scale + ty);
      ctx.fillStyle = "#0b0e14";
      ctx.fillRect(0, 0, W, H);

      const vs = visible();
      let profileDrawn = false;
      for (const o of vs) {
        ctx.lineWidth = 0.6;
        for (const poly of o.geom.polygons as Ring[]) {
          const c = poly.color ?? o.color;
          ctx.fillStyle = c + "88";
          ctx.strokeStyle = c;
          ctx.beginPath();
          ring(poly.exterior, toX, toY);
          for (const h of poly.holes) ring(h, toX, toY);
          ctx.fill("evenodd");
          ctx.stroke();
        }
        if (o.geom.points && o.geom.points.length) {
          ctx.fillStyle = "#ffd54f";
          for (const [px, py] of o.geom.points) ctx.fillRect(toX(px) - 1, toY(py) - 1, 2, 2);
        }
        if (!profileDrawn && o.geom.profile?.length) {
          ctx.strokeStyle = "#8a8a8a";
          ctx.lineWidth = 1.2;
          for (const p of o.geom.profile) { ctx.beginPath(); ring(p.exterior, toX, toY); ctx.stroke(); }
          profileDrawn = true;
        }
      }

      // refdes labels (component overlays) when zoomed in
      if (labels.current && view.current.scale >= LABEL_MIN_SCALE) {
        ctx.fillStyle = "#eaeaea";
        ctx.font = "10px system-ui";
        ctx.textAlign = "center";
        for (const o of vs) {
          for (const poly of o.geom.polygons as Ring[]) {
            if (!poly.meta) continue;
            const ex = poly.exterior;
            let cx = 0, cy = 0;
            for (const [x, y] of ex) { cx += x; cy += y; }
            cx /= ex.length; cy /= ex.length;
            ctx.fillText(poly.meta.refdes, toX(cx), toY(cy));
          }
        }
      }
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = cv.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const { scale, tx, ty } = view.current;
      const wx = (mx - tx) / scale, wy = (H - my - ty) / scale;
      const ns = scale * (e.deltaY < 0 ? 1.1 : 1 / 1.1);
      view.current = { scale: ns, tx: mx - wx * ns, ty: H - my - wy * ns };
      draw();
    };
    const onDown = (e: MouseEvent) => {
      drag.current = { sx: e.clientX, sy: e.clientY, tx: view.current.tx, ty: view.current.ty, moved: false };
    };
    const onMove = (e: MouseEvent) => {
      const rect = cv.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      if (coordRef.current && mx >= 0 && my >= 0 && mx <= W && my <= H) {
        const { scale, tx, ty } = view.current;
        const wx = (mx - tx) / scale, wy = (H - my - ty) / scale;
        coordRef.current.textContent = `x: ${wx.toFixed(3)}  y: ${wy.toFixed(3)} mm`;
      }
      if (!drag.current) return;
      const dx = e.clientX - drag.current.sx, dy = e.clientY - drag.current.sy;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.current.moved = true;
      view.current.tx = drag.current.tx + dx;
      view.current.ty = drag.current.ty - dy;
      draw();
    };
    const onUp = (e: MouseEvent) => {
      const d = drag.current;
      drag.current = null;
      if (!onPick || !d || d.moved) return;
      // Treat as click: hit-test component polygons (those carrying meta).
      const rect = cv.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      if (mx < 0 || my < 0 || mx > W || my > H) return;
      const { scale, tx, ty } = view.current;
      const wx = (mx - tx) / scale, wy = (H - my - ty) / scale;
      for (const o of visible()) {
        for (const poly of o.geom.polygons as Ring[]) {
          if (poly.meta && pointInRing(wx, wy, poly.exterior)) {
            onPick(poly.meta);
            return;
          }
        }
      }
      onPick(null);
    };

    fit();
    draw();
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      cv.removeEventListener("wheel", onWheel);
      cv.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // Re-fit/redraw when the visible scene or fit request changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlays, fitToken]);

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <canvas
        ref={ref}
        width={W}
        height={H}
        style={{ border: "1px solid #333", cursor: "grab", maxWidth: "100%" }}
      />
      <span
        ref={coordRef}
        style={{
          position: "absolute", left: 8, bottom: 8, color: "#9fe",
          background: "rgba(0,0,0,0.5)", padding: "1px 6px", borderRadius: 4,
          fontSize: 12, fontFamily: "monospace", pointerEvents: "none",
        }}
      />
    </div>
  );
}
