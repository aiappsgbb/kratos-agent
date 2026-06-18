/** @type {import('next').NextConfig} */

// Optional sub-path mount (e.g. "/kratos") so the static export can be hosted
// under a path of another origin (Front Door) without copying Kratos files.
// Empty/unset → mounted at the origin root (standalone deployment).
const rawBasePath = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");
const basePath = rawBasePath.startsWith("/") ? rawBasePath : rawBasePath ? `/${rawBasePath}` : "";

const nextConfig = {
  output: "export",
  trailingSlash: true,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  images: {
    unoptimized: true,
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "",
    NEXT_PUBLIC_BASE_PATH: basePath,
    NEXT_PUBLIC_MSAL_CLIENT_ID: process.env.NEXT_PUBLIC_MSAL_CLIENT_ID || "",
    NEXT_PUBLIC_MSAL_AUTHORITY: process.env.NEXT_PUBLIC_MSAL_AUTHORITY || "",
  },
};

module.exports = nextConfig;
