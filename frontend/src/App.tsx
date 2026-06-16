import { Input, Layout, Menu, Tooltip } from "antd";
import {
  DashboardOutlined,
  ExportOutlined,
  CheckSquareOutlined,
  PercentageOutlined,
  BorderOuterOutlined,
  EyeOutlined,
  DiffOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { useUser } from "./UserContext";
import Dashboard from "./pages/Dashboard";
import Checklist from "./pages/Checklist";
import Copper from "./pages/Copper";
import Extract from "./pages/Extract";
import Interposer from "./pages/Interposer";
import Compare from "./pages/Compare";
import Viewer from "./pages/Viewer";

const { Header, Sider, Content } = Layout;

function selectedKey(pathname: string): string {
  if (pathname.startsWith("/checklist")) return "checklist";
  if (pathname.startsWith("/copper")) return "copper";
  if (pathname.startsWith("/extract")) return "extract";
  if (pathname.startsWith("/interposer")) return "interposer";
  if (pathname.startsWith("/compare")) return "compare";
  if (pathname.startsWith("/viewer")) return "viewer";
  return "dashboard";
}

export default function App() {
  const loc = useLocation();
  const selected = selectedKey(loc.pathname);
  const { user, setUserName } = useUser();

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          fontSize: 18,
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Link to="/" style={{ color: "#fff" }}>
          ODB++ 자동화 허브
        </Link>
        <Tooltip title="사용자 이름 (작업 소유자 표시 / 내 작업 필터에 사용)">
          <Input
            size="small"
            prefix={<UserOutlined />}
            placeholder="사용자 이름"
            defaultValue={user}
            onBlur={(e) => setUserName(e.target.value)}
            onPressEnter={(e) => setUserName((e.target as HTMLInputElement).value)}
            style={{ width: 180 }}
          />
        </Tooltip>
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
              { key: "viewer", icon: <EyeOutlined />, label: <Link to="/viewer">ODB 뷰어</Link> },
              { key: "compare", icon: <DiffOutlined />, label: <Link to="/compare">리비전 비교</Link> },
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
            <Route path="/viewer" element={<Viewer />} />
            <Route path="/compare" element={<Compare />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}
