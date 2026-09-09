/// <reference types="vite/client" />

declare module "pdfjs-dist/build/pdf.mjs" {
  export const GlobalWorkerOptions: {
    workerSrc: string;
  };

  export function getDocument(source: { data: Uint8Array }): {
    destroy(): Promise<void>;
    promise: Promise<{
      numPages: number;
      getPage(pageNumber: number): Promise<{
        getViewport(params: { scale: number }): { width: number };
        getTextContent(): Promise<{
          items?: Array<{
            str?: string;
            dir?: string;
            transform?: number[];
            width?: number;
            height?: number;
          }>;
        }>;
      }>;
    }>;
  };
}
