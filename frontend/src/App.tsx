import { Layout, Menu } from "antd";
import { Link, Route, Routes, useLocation } from "react-router-dom";
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

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ color: "#fff", fontSize: 18, fontWeight: 600 }}>
        ODB++ 자동화 허브
      </Header>
      <Layout>
        <Sider width={200} theme="light">
          <Menu
            mode="inline"
            selectedKeys={[selected]}
            style={{ height: "100%" }}
            items={[
              { key: "dashboard", label: <Link to="/">대시보드</Link> },
              { key: "extract", label: <Link to="/extract">Extract</Link> },
              { key: "checklist", label: <Link to="/checklist">체크리스트</Link> },
              { key: "copper", label: <Link to="/copper">Copper</Link> },
              { key: "interposer", label: <Link to="/interposer">Interposer</Link> },
              { key: "viewer", label: <Link to="/viewer">Viewer</Link> },
              { key: "compare", label: <Link to="/compare">비교</Link> },
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
