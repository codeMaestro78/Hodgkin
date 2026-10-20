import type { MetadataRoute } from "next";
import { appOrigin } from "../lib/auth/config";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/api/", "/auth/", "/research", "/onboarding", "/reset-password"],
    },
    sitemap: `${appOrigin()}/sitemap.xml`,
  };
}
