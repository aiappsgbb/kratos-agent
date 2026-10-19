/** @type {import('next').NextConfig} */

// Optional sub-path mount (e.g. "/kratos") so the app can be hosted under a
// path of another origin (Front Door) without copying Kratos files.
// Empty/unset → mounted at the origin root (standalone deployment).
const rawBasePath = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");
const basePath = rawBasePath.startsWith("/") ? rawBasePath : rawBasePath ? `/${rawBasePath}` : "";

// Same policy the Static Web App used to set. connect-src is 'self' plus the
// backends the browser calls directly (admin REST API, Entra sign-in) and a
// loopback backend for local runs; agent runs use the same-origin runtime route.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "connect-src 'self' http://localhost:* http://127.0.0.1:* https://login.microsoftonline.com https://*.azurecontainerapps.io https://*.azure-api.net https://*.cognitiveservices.azure.com",
      "img-src 'self' https://*.azurecontainerapps.io https://*.azure-api.net data: blob:",
      "frame-src 'self' https://login.microsoftonline.com https://*.azurecontainerapps.io https://*.azure-api.net",
    ].join("; "),
  },
];

const nextConfig = {
  // A Node server (not a static export): it hosts the CopilotKit runtime route
  // that relays AG-UI runs to the backend, and serves config.json from env.
  output: "standalone",
  devIndicators: false,
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
  webpack(config, { webpack }) {
    // CopilotKit's v2 entry imports its prebuilt Tailwind v4 stylesheet. The UI
    // is headless (Kratos components only), and Tailwind v3's PostCSS plugin
    // rejects that file, so swap it for an empty one.
    config.plugins.push(
      new webpack.NormalModuleReplacementPlugin(
        /@copilotkit[\\/]react-core[\\/]dist[\\/]v2[\\/]index\.css$/,
        require.resolve("./src/styles/copilotkit-headless.css"),
      ),
    );
    return config;
  },
  async headers() {
    // `next dev` needs eval for fast refresh, which this CSP forbids.
    if (process.env.NODE_ENV !== "production") return [];
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

module.exports = nextConfig;
