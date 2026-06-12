import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  // Production: static export served by FastAPI from web-next/out/
  ...(isDev ? {} : { output: "export" as const }),
  trailingSlash: true,   // emit convert/index.html so StaticFiles can serve it
  images: { unoptimized: true },
  // Dev only: proxy API calls to the FastAPI server (rewrites are ignored in export)
  async rewrites() {
    return isDev
      ? [{ source: "/api/:path*", destination: "http://127.0.0.1:8178/api/:path*" }]
      : [];
  },
};

export default nextConfig;
