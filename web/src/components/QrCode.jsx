import { useMemo } from 'react';
import qrcode from 'qrcode-generator';

const QUIET_ZONE = 4;

// Builds the QR code as SVG rectangles (one per dark module). No raw HTML injection, no data URLs.
export default function QrCode({ value }) {
  const { size, rects } = useMemo(() => {
    const q = qrcode(0, 'M');
    q.addData(value);
    q.make();
    const n = q.getModuleCount();
    const cells = [];
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (q.isDark(r, c)) {
          cells.push(
            <rect key={`${r}:${c}`} x={c + QUIET_ZONE} y={r + QUIET_ZONE} width="1" height="1" fill="#000" />,
          );
        }
      }
    }
    return { size: n + 2 * QUIET_ZONE, rects: cells };
  }, [value]);

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className="size-40 shrink-0 rounded-md bg-white p-1"
      shapeRendering="crispEdges"
      role="img"
      aria-label="QR-код ссылки"
    >
      <rect x="0" y="0" width={size} height={size} fill="#fff" />
      {rects}
    </svg>
  );
}
