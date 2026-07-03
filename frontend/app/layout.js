import "./globals.css";

export const metadata = {
  title: "ClipMind AI — Viral Stream Clipper",
  description: "Never miss a viral moment again.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
