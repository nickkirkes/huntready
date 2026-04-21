import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "HuntReady",
  description: "Regulatory data platform for licensed hunting in the US",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
