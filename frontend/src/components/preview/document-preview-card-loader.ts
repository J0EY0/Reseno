import { createRouteLoader } from "@/lib/route-loader";

export const loadDocumentPreviewCard = createRouteLoader(
  () => import("@/components/preview/document-preview-card"),
  "DocumentPreviewCard",
);
