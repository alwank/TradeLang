import type { Metadata } from "next";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./styles.css";
import { Shell } from "@/components/shell";

const applyTheme = `try {
  if (JSON.parse(localStorage.getItem("tradelang.display.v1"))?.theme === "light") {
    document.documentElement.dataset.theme = "light";
  }
} catch {}`;

export const metadata: Metadata = {
  title: { default: "TradeLang", template: "%s · TradeLang" },
  description: "Write, run, and inspect local TradeLang backtests.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: applyTheme }} /></head>
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
