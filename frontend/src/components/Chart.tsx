import { useState } from "react";
import { brl, shortDate } from "../lib/format";
import type { Variant } from "../lib/types";

export function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${26 - ((v - min) / span) * 22}`)
    .join(" ");
  const down = values[values.length - 1] <= values[0];
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-8 w-24" aria-hidden>
      <polyline
        points={points}
        fill="none"
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
        className={down ? "stroke-good" : "stroke-warn"}
      />
    </svg>
  );
}

const W = 600;
const H = 220;
const PAD = { top: 14, right: 12, bottom: 24, left: 64 };

export function PriceChart({ history }: { history: Variant["history"] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (history.length < 2) {
    return (
      <p className="py-8 text-center text-sm text-muted">
        O gráfico aparece quando houver pelo menos dois dias de histórico.
      </p>
    );
  }
  const prices = history.map((h) => h.price);
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  const margin = (high - low) * 0.12 || high * 0.05;
  const min = Math.max(0, low - margin);
  const max = high + margin;
  const times = history.map((h) => new Date(h.day).getTime());
  const x = (i: number) =>
    PAD.left +
    ((times[i] - times[0]) / (times[times.length - 1] - times[0] || 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - min) / (max - min)) * (H - PAD.top - PAD.bottom);
  const line = history.map((h, i) => `${x(i)},${y(h.price)}`).join(" ");
  const point = hover ?? history.length - 1;

  return (
    <figure>
      <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span>
          <strong>{brl(history[point].price)}</strong>{" "}
          <span className="text-muted">
            em {shortDate(history[point].day)} · {history[point].store}
          </span>
        </span>
        <span className="text-muted">
          Menor: <strong className="text-good">{brl(low)}</strong> · Maior: {brl(high)}
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-pan-y"
        role="img"
        aria-label={`Histórico de preços: de ${brl(low)} a ${brl(high)}`}
        onPointerLeave={() => setHover(null)}
        onPointerMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const target = ((event.clientX - box.left) / box.width) * W;
          let nearest = 0;
          history.forEach((_, i) => {
            if (Math.abs(x(i) - target) < Math.abs(x(nearest) - target)) nearest = i;
          });
          setHover(nearest);
        }}
      >
        <defs>
          <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#8b5cf6" stopOpacity="0.35" />
            <stop offset="1" stopColor="#8b5cf6" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((f) => {
          const value = min + (max - min) * f;
          return (
            <g key={f}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(value)} y2={y(value)} className="stroke-line" />
              <text x={PAD.left - 8} y={y(value) + 4} textAnchor="end" className="fill-muted text-[11px]">
                {Math.round(value).toLocaleString("pt-BR")}
              </text>
            </g>
          );
        })}
        <polygon
          points={`${x(0)},${H - PAD.bottom} ${line} ${x(history.length - 1)},${H - PAD.bottom}`}
          fill="url(#area)"
        />
        <polyline points={line} fill="none" stroke="#8b5cf6" strokeWidth="2.5" strokeLinejoin="round" />
        <line x1={x(point)} x2={x(point)} y1={PAD.top} y2={H - PAD.bottom} className="stroke-muted" strokeDasharray="3 4" />
        <circle cx={x(point)} cy={y(history[point].price)} r="5" fill="#ec4899" />
        <text x={PAD.left} y={H - 6} className="fill-muted text-[11px]">
          {shortDate(history[0].day)}
        </text>
        <text x={W - PAD.right} y={H - 6} textAnchor="end" className="fill-muted text-[11px]">
          {shortDate(history[history.length - 1].day)}
        </text>
      </svg>
    </figure>
  );
}
