/// <reference types="vite/client" />

declare module "pdfjs-dist/build/pdf.mjs" {
  export const GlobalWorkerOptions: {
    workerSrc: string;
  };

  export function getDocument(source: {
    data: Uint8Array;
  }): {
    promise: Promise<{
      numPages: number;
      getPage(pageNumber: number): Promise<{
        getTextContent(): Promise<{
          items?: Array<{
            str?: string;
            transform?: number[];
            width?: number;
            height?: number;
          }>;
        }>;
      }>;
    }>;
  };
}
