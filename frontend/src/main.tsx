import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntdApp, ConfigProvider } from "antd";
import App from "./App";
import { JobProvider } from "./JobContext";
import { UserProvider } from "./UserContext";
import "antd/dist/reset.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AntdApp>
          <UserProvider>
            <JobProvider>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </JobProvider>
          </UserProvider>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
