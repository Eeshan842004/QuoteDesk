"use client";

import {
  CartesianGrid,
  LabelList,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const axis = { stroke: "var(--viz-axis)", tick: { fill: "var(--viz-muted)", fontSize: 11 }, tickLine: false };
const tooltipStyle = {
  contentStyle: {
    background: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    fontSize: 12,
    color: "var(--popover-foreground)",
  },
  labelStyle: { color: "var(--viz-ink-2)" },
};

export interface SystemPoint {
  name: string;
  cost: number;
  f1: number;
}

/** Accuracy vs cost: one hue, every point directly labelled (identity never relies on color). */
export function AccuracyCostChart({ points }: { points: SystemPoint[] }) {
  const data = points.filter((p) => p.cost > 0 && p.f1 != null);
  if (!data.length) return <p className="text-sm text-muted-foreground">Cost data not available yet.</p>;
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 16, right: 150, bottom: 28, left: 8 }}>
          <CartesianGrid stroke="var(--viz-grid)" vertical={false} />
          <XAxis
            type="number"
            dataKey="cost"
            name="Cost per 1,000 emails"
            scale="log"
            domain={["auto", "auto"]}
            tickFormatter={(v: number) => `$${v < 1 ? v.toFixed(2) : v.toFixed(0)}`}
            label={{ value: "cost per 1,000 emails (log scale)", position: "insideBottom", offset: -16, fill: "var(--viz-muted)", fontSize: 11 }}
            {...axis}
          />
          <YAxis
            type="number"
            dataKey="f1"
            name="Item F1"
            domain={[Math.max(0, Math.floor((Math.min(...data.map((d) => d.f1)) - 0.03) * 20) / 20), 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            width={44}
            {...axis}
          />
          <Tooltip
            {...tooltipStyle}
            cursor={{ stroke: "var(--viz-axis)", strokeDasharray: "3 3" }}
            formatter={(v, n) => (n === "Item F1" ? `${(Number(v) * 100).toFixed(1)}%` : `$${Number(v).toFixed(3)}`)}
            labelFormatter={() => ""}
          />
          <Scatter isAnimationActive={false} data={data} fill="var(--viz-1)" stroke="var(--card)" strokeWidth={2} shape="circle" legendType="none">
            <LabelList dataKey="name" position="right" offset={10} style={{ fill: "var(--foreground)", fontSize: 11 }} />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

interface SweepRow {
  threshold: number;
  item_f1: number;
  escalation_rate: number;
  cost_per_1k_usd: number;
}

/** Router sweep: item F1 and % escalated share one 0-100% axis (two series, legend + direct labels). */
export function SweepQualityChart({ sweep, chosen }: { sweep: SweepRow[]; chosen: number }) {
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <LineChart data={sweep} margin={{ top: 40, right: 24, bottom: 28, left: 8 }}>
          <CartesianGrid stroke="var(--viz-grid)" vertical={false} />
          <XAxis
            dataKey="threshold"
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => v.toFixed(1)}
            label={{ value: "router confidence threshold", position: "insideBottom", offset: -16, fill: "var(--viz-muted)", fontSize: 11 }}
            {...axis}
          />
          <YAxis domain={[0, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} width={44} {...axis} />
          <Tooltip {...tooltipStyle} formatter={(v) => `${(Number(v) * 100).toFixed(1)}%`} labelFormatter={(v) => `threshold ${Number(v).toFixed(2)}`} />
          <Legend verticalAlign="top" height={24} iconType="plainline" wrapperStyle={{ fontSize: 12, top: 0 }} />
          <ReferenceLine x={chosen} stroke="var(--viz-ink-2)" strokeDasharray="4 4" label={{ value: `chosen ${chosen.toFixed(2)}`, position: "top", fill: "var(--viz-ink-2)", fontSize: 11 }} />
          <Line isAnimationActive={false} type="monotone" dataKey="item_f1" name="item F1" stroke="var(--viz-1)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
          <Line isAnimationActive={false} type="monotone" dataKey="escalation_rate" name="% escalated" stroke="var(--viz-2)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Cost per 1,000 emails across thresholds: its own chart (never a second y-axis). */
export function SweepCostChart({ sweep, chosen }: { sweep: SweepRow[]; chosen: number }) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer>
        <LineChart data={sweep} margin={{ top: 16, right: 24, bottom: 28, left: 8 }}>
          <CartesianGrid stroke="var(--viz-grid)" vertical={false} />
          <XAxis
            dataKey="threshold"
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => v.toFixed(1)}
            label={{ value: "router confidence threshold", position: "insideBottom", offset: -16, fill: "var(--viz-muted)", fontSize: 11 }}
            {...axis}
          />
          <YAxis tickFormatter={(v: number) => `$${v.toFixed(2)}`} width={52} {...axis} />
          <Tooltip {...tooltipStyle} formatter={(v) => `$${Number(v).toFixed(3)} per 1k`} labelFormatter={(v) => `threshold ${Number(v).toFixed(2)}`} />
          <ReferenceLine x={chosen} stroke="var(--viz-ink-2)" strokeDasharray="4 4" />
          <Line isAnimationActive={false} type="monotone" dataKey="cost_per_1k_usd" name="cost per 1k" stroke="var(--viz-1)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
