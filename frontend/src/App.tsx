import { Layout, Menu } from "antd";
import {
  DashboardOutlined,
  ExportOutlined,
  CheckSquareOutlined,
  PercentageOutlined,
  BorderOuterOutlined,
  ColumnHeightOutlined,
  EyeOutlined,
  DiffOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Checklist from "./pages/Checklist";
import Copper from "./pages/Copper";
import Extract from "./pages/Extract";
import Interposer from "./pages/Interposer";
import Volume from "./pages/Volume";
import Compare from "./pages/Compare";
import Viewer from "./pages/Viewer";
import Activity from "./pages/Activity";

const { Header, Sider, Content } = Layout;

function selectedKey(pathname: string): string {
  if (pathname.startsWith("/checklist")) return "checklist";
  if (pathname.startsWith("/copper")) return "copper";
  if (pathname.startsWith("/extract")) return "extract";
  if (pathname.startsWith("/interposer")) return "interposer";
  if (pathname.startsWith("/volume")) return "volume";
  if (pathname.startsWith("/compare")) return "compare";
  if (pathname.startsWith("/viewer")) return "viewer";
  if (pathname.startsWith("/activity")) return "activity";
  return "dashboard";
}

export default function App() {
  const loc = useLocation();
  const selected = selectedKey(loc.pathname);

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          fontSize: 18,
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
        }}
      >
        <Link to="/" style={{ color: "#fff" }}>
          ODB++ 자동화 허브
        </Link>
      </Header>
      <Layout>
        <Sider width={230} theme="light">
          <Menu
            mode="inline"
            selectedKeys={[selected]}
            style={{ height: "100%" }}
            items={[
              { key: "dashboard", icon: <DashboardOutlined />, label: <Link to="/">대시보드</Link> },
              { key: "extract", icon: <ExportOutlined />, label: <Link to="/extract">데이터 추출</Link> },
              { key: "checklist", icon: <CheckSquareOutlined />, label: <Link to="/checklist">체크리스트</Link> },
              { key: "copper", icon: <PercentageOutlined />, label: <Link to="/copper">동박율 계산</Link> },
              { key: "interposer", icon: <BorderOuterOutlined />, label: <Link to="/interposer">인터포저 영역 계산</Link> },
              { key: "volume", icon: <ColumnHeightOutlined />, label: <Link to="/volume">PCB 부품 부피 계산</Link> },
              { key: "viewer", icon: <EyeOutlined />, label: <Link to="/viewer">ODB 뷰어</Link> },
              { key: "compare", icon: <DiffOutlined />, label: <Link to="/compare">리비전 비교</Link> },
              { key: "activity", icon: <TeamOutlined />, label: <Link to="/activity">사용자 현황</Link> },
            ]}
          />
        </Sider>
        <Content style={{ padding: 24 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/extract" element={<Extract />} />
            <Route path="/checklist" element={<Checklist />} />
            <Route path="/copper" element={<Copper />} />
            <Route path="/interposer" element={<Interposer />} />
            <Route path="/volume" element={<Volume />} />
            <Route path="/viewer" element={<Viewer />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/activity" element={<Activity />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}
