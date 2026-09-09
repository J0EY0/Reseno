export function readAvatarFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
        return;
      }

      reject(new Error("Failed to read avatar file as a data URL."));
    };

    reader.onerror = () => {
      reject(reader.error ?? new Error("Failed to read avatar file."));
    };

    reader.readAsDataURL(file);
  });
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function loadImage(source: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();

    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Failed to load avatar image."));
    image.src = source;
  });
}

export async function cropAvatarDataUrl(
  source: string,
  {
    cropX,
    cropY,
    cropWidth,
    cropHeight,
    outputWidth = 800,
    outputHeight = 1000,
  }: {
    cropX: number;
    cropY: number;
    cropWidth: number;
    cropHeight: number;
    outputWidth?: number;
    outputHeight?: number;
  },
) {
  if (typeof document === "undefined") {
    return source;
  }

  const image = await loadImage(source);
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");

  if (!context) {
    return source;
  }

  const safeWidth = clamp(cropWidth, 1, image.naturalWidth);
  const safeHeight = clamp(cropHeight, 1, image.naturalHeight);
  const safeX = clamp(cropX, 0, image.naturalWidth - safeWidth);
  const safeY = clamp(cropY, 0, image.naturalHeight - safeHeight);

  canvas.width = outputWidth;
  canvas.height = outputHeight;

  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, outputWidth, outputHeight);
  context.drawImage(
    image,
    safeX,
    safeY,
    safeWidth,
    safeHeight,
    0,
    0,
    outputWidth,
    outputHeight,
  );

  return canvas.toDataURL("image/jpeg", 0.92);
}
