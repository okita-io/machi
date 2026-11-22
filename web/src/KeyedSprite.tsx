import { useEffect, useState } from "react";
import { keyChromaPixels } from "./chroma";

const keyed = new Map<string, Promise<string>>();

/** Decode once, key green to alpha, and reuse the PNG blob URL. */
function keySprite(src: string): Promise<string> {
  const cached = keyed.get(src);
  if (cached) return cached;
  const job = new Promise<string>((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("canvas"));
        return;
      }
      ctx.drawImage(img, 0, 0);
      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
      keyChromaPixels(frame.data);
      ctx.putImageData(frame, 0, 0);
      canvas.toBlob((blob) => {
        if (!blob) {
          reject(new Error("blob"));
          return;
        }
        resolve(URL.createObjectURL(blob));
      }, "image/png");
    };
    img.onerror = () => reject(new Error("sprite"));
    img.src = src;
  });
  keyed.set(src, job);
  return job;
}

export function KeyedSprite({ src, expression }: { src: string; expression: string }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    setUrl(null);
    keySprite(src).then(
      (next) => {
        if (!cancel) setUrl(next);
      },
      () => {
        if (!cancel) setUrl(src);
      },
    );
    return () => {
      cancel = true;
    };
  }, [src]);

  return (
    <img
      className="guide"
      src={url ?? undefined}
      alt="Sora"
      data-expression={expression}
      hidden={!url}
    />
  );
}
