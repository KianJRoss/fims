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

export default function ProductImage({ imageUrl, name, size = "sm", className = "" }: Props) {
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  const dims = sizeMap[size];

  if (!imageUrl) {
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
        src={imageUrl}
        alt={name}
        className="h-full w-full object-contain p-1"
        onError={(e) => {
          const wrap = e.currentTarget.parentElement as HTMLElement;
          e.currentTarget.style.display = "none";
          const fb = document.createElement("span");
          fb.className = "text-gray-500 font-bold text-sm";
          fb.textContent = initial;
          wrap.appendChild(fb);
        }}
      />
    </div>
  );
}
