import { readAvatarFileAsDataUrl } from "@/lib/avatar";

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_INLINE_BYTES = 1024 * 1024;
const MAX_INPUT_PIXELS = 40_000_000;
const MAX_INPUT_EDGE = 16_384;
const MAX_OUTPUT_EDGE = Math.ceil((120 / 25.4) * 300);

function assertDimensions(width: number, height: number) {
  if (
    !width ||
    !height ||
    width > MAX_INPUT_EDGE ||
    height > MAX_INPUT_EDGE ||
    width * height > MAX_INPUT_PIXELS
  ) {
    throw new Error("templateImageTooManyPixels");
  }
}

async function readImageFormat(file: File) {
  const header = new DataView(await file.slice(0, 32).arrayBuffer());
  const text = (offset: number, length: number) => {
    if (offset + length > header.byteLength) return "";
    return String.fromCharCode(
      ...new Uint8Array(header.buffer, offset, length),
    );
  };
  if (text(1, 3) === "PNG" && header.byteLength >= 24) {
    assertDimensions(header.getUint32(16), header.getUint32(20));
    let offset = 8;
    while (offset + 12 <= file.size) {
      const chunk = new DataView(
        await file.slice(offset, offset + 8).arrayBuffer(),
      );
      const type = String.fromCharCode(...new Uint8Array(chunk.buffer, 4, 4));
      if (type === "acTL") return "original";
      if (type === "IDAT") break;
      offset += chunk.getUint32(0) + 12;
    }
    return "png";
  }
  if (text(0, 3) === "GIF" && header.byteLength >= 10) {
    assertDimensions(header.getUint16(6, true), header.getUint16(8, true));
    return "original";
  }
  if (
    text(0, 4) === "RIFF" &&
    text(8, 4) === "WEBP" &&
    text(12, 4) === "VP8X" &&
    header.byteLength >= 30
  ) {
    if (header.getUint8(20) & 2) return "original";
  }
  if (file.type === "image/svg+xml" || text(8, 4) === "avis") return "original";
  return header.byteLength >= 3 &&
    header.getUint8(0) === 0xff &&
    header.getUint8(1) === 0xd8 &&
    header.getUint8(2) === 0xff
    ? "jpeg"
    : "png";
}

function loadImage(source: string, image: HTMLImageElement) {
  return new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("templateImageInvalidFile"));
    image.src = source;
  });
}

function getEncodedBytes(source: string) {
  const padding = source.endsWith("==") ? 2 : source.endsWith("=") ? 1 : 0;
  return ((source.length - source.indexOf(",") - 1) * 3) / 4 - padding;
}

export async function prepareTemplateImage(file: File): Promise<string> {
  if (!file.type.startsWith("image/") || file.size === 0) {
    throw new Error("templateImageInvalidFile");
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("templateImageTooLarge");
  }
  const format = await readImageFormat(file);
  if (format === "original" && file.size > MAX_INLINE_BYTES) {
    throw new Error("templateImageOriginalTooLarge");
  }
  const source = await readAvatarFileAsDataUrl(file);
  const image = new Image();
  const canvas = document.createElement("canvas");
  try {
    await loadImage(source, image);
    assertDimensions(image.naturalWidth, image.naturalHeight);
    if (format === "original") return source;
    const scale = Math.min(
      1,
      MAX_OUTPUT_EDGE / image.naturalWidth,
      MAX_OUTPUT_EDGE / image.naturalHeight,
    );
    if (scale === 1 && file.size <= MAX_INLINE_BYTES) return source;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("templateImageProcessingFailed");
    let width = Math.max(1, Math.round(image.naturalWidth * scale));
    let height = Math.max(1, Math.round(image.naturalHeight * scale));
    while (true) {
      canvas.width = width;
      canvas.height = height;
      context.imageSmoothingQuality = "high";
      context.drawImage(image, 0, 0, width, height);
      const output = canvas.toDataURL(
        format === "jpeg" ? "image/jpeg" : "image/png",
        0.9,
      );
      if (output === "data:,") throw new Error("templateImageProcessingFailed");
      const byteLength = getEncodedBytes(output);
      if (byteLength <= MAX_INLINE_BYTES) return output;
      const reduction = Math.min(
        0.9,
        Math.sqrt(MAX_INLINE_BYTES / byteLength) * 0.9,
      );
      width = Math.max(1, Math.floor(width * reduction));
      height = Math.max(1, Math.floor(height * reduction));
      if (width === 1 && height === 1)
        throw new Error("templateImageProcessingFailed");
    }
  } finally {
    canvas.width = 0;
    canvas.height = 0;
    image.onload = null;
    image.onerror = null;
    image.src = "";
  }
}
