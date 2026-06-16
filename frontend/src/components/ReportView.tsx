import { Button, Space } from "antd";
import { DownloadOutlined, SelectOutlined } from "@ant-design/icons";

// Embeds an HTML report (served by the backend) and offers new-tab + download.
export default function ReportView({
  src,
  height = "78vh",
  downloadName = "report.html",
}: {
  src: string;
  height?: number | string;
  downloadName?: string;
}) {
  // `?download=1` makes the backend send Content-Disposition: attachment; the
  // anchor `download` attribute forces a save (with this name) even otherwise.
  const dlSrc = src + (src.includes("?") ? "&" : "?") + "download=1";
  return (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Button icon={<SelectOutlined />} href={src} target="_blank">
          새 탭에서 열기
        </Button>
        <Button icon={<DownloadOutlined />} href={dlSrc} download={downloadName}>
          다운로드
        </Button>
      </Space>
      <iframe
        title="report"
        src={src}
        style={{ width: "100%", height, border: "1px solid #eee" }}
      />
    </div>
  );
}
