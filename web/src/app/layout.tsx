import type { Metadata } from "next";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "星上智能计算数字孪生",
  description: "Satellite onboard AI software-in-the-loop digital twin"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}

