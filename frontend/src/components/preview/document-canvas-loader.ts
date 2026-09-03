import { createRouteLoader } from "@/lib/route-loader";

export const loadDocumentCanvas = createRouteLoader(
  () => import("@/components/preview/document-canvas"),
  "DocumentCanvas",
);
