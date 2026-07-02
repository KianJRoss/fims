import { useEffect, useState } from "react";

type Props = {
  imageUrl: string | null | undefined;
  name: string;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
};

const sizeMap = {
  xs: "h-10 w-10",
  sm: "h-14 w-14",
  md: "h-20 w-20",
  lg: "h-40 w-full",
};

/** Thumbnail path for a product image: /media/product_images/X.jpg -> .../thumbs/X.webp */
export function productThumbUrl(imageUrl: string): string | null {
  const match = imageUrl.match(/^(.*\/product_images)\/([^/]+)\.[a-zA-Z0-9]+$/);
  if (!match) return null;
  return `${match[1]}/thumbs/${match[2]}.webp`;
}

export default function ProductImage({ imageUrl, name, size = "sm", className = "" }: Props) {
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  const dims = sizeMap[size];

  // Try the small thumbnail first; fall back to the original, then the letter.
  const thumb = imageUrl ? productThumbUrl(imageUrl) : null;
  const sources = imageUrl ? (thumb ? [thumb, imageUrl] : [imageUrl]) : [];
  const [sourceIndex, setSourceIndex] = useState(0);
  useEffect(() => {
    setSourceIndex(0);
  }, [imageUrl]);

  if (!imageUrl || sourceIndex >= sources.length) {
    return (
      <div
        className={`${dims} flex-shrink-0 flex items-center justify-center rounded-xl bg-gray-800 text-gray-500 font-bold text-sm ${className}`}
      >
        {initial}
      </div>
    );
  }

  return (
    <div className={`${dims} flex-shrink-0 flex items-center justify-center rounded-xl bg-gray-800 overflow-hidden ${className}`}>
      <img
        src={sources[sourceIndex]}
        alt={name}
        loading="lazy"
        decoding="async"
        className="h-full w-full object-contain p-1"
        onError={() => setSourceIndex((index) => index + 1)}
      />
    </div>
  );
}
