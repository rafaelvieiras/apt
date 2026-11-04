import { defineConfig } from "astro/config";

// Static output, one HTML file per page (`packages.html`, no folders). The uploader in
// aptrepo/site.py also stores each page under its extensionless key, so `/packages`
// works behind a bucket that serves no index documents.
export default defineConfig({
  output: "static",
  trailingSlash: "never",
  build: {
    format: "file",
    inlineStylesheets: "always",
  },
  devToolbar: { enabled: false },
  server: { host: "127.0.0.1" },
  telemetry: false,
});
