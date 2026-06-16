import { Button, Space } from "antd";

// Embeds an HTML report (served by the backend) and offers a new-tab link.
export default function ReportView({ src }: { src: string }) {
  return (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Button href={src} target="_blank">
          새 탭에서 열기
        </Button>
      </Space>
      <iframe
        title="report"
        src={src}
        style={{ width: "100%", height: 600, border: "1px solid #eee" }}
      />
    </div>
  );
}
