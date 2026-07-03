/** @type {import('next').NextConfig} */
const API = process.env.NEXT_PUBLIC_API || "http://127.0.0.1:8000";
module.exports = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
      { source: "/clips/:path*", destination: `${API}/clips/:path*` },
    ];
  },
};
