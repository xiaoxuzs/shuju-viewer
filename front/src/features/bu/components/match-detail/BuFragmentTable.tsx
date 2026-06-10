import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuMatchedIon } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";

export function BuFragmentTable({ ions }: { ions: BuMatchedIon[] }) {
  if (ions.length === 0) return null;
  const sorted = [...ions].sort((a, b) => a.ion_type.localeCompare(b.ion_type) || a.position - b.position || a.charge - b.charge);

  return (
    <Card className="mt-4 border-border/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Live mzML matched b/y fragments ({formatCount(ions.length)})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-border text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="py-2 text-left">Ion</th>
                <th className="py-2 text-right">Position</th>
                <th className="py-2 text-right">Charge</th>
                <th className="py-2 text-right">Theo m/z</th>
                <th className="py-2 text-right">Exp m/z</th>
                <th className="py-2 text-right">ppm</th>
                <th className="py-2 text-right">Intensity</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((ion, index) => (
                <tr key={`${ion.ion_type}-${ion.position}-${ion.charge}-${ion.exp_mz}-${index}`} className="border-b border-border/60 last:border-0">
                  <td className="py-2 font-mono font-medium">{ionLabel(ion)}</td>
                  <td className="py-2 text-right">{ion.position}</td>
                  <td className="py-2 text-right">{ion.charge}+</td>
                  <td className="py-2 text-right font-mono text-xs">{formatDecimal(ion.theo_mz)}</td>
                  <td className="py-2 text-right font-mono text-xs">{formatDecimal(ion.exp_mz)}</td>
                  <td className="py-2 text-right font-mono text-xs">{formatDecimal(ion.ppm, 2)}</td>
                  <td className="py-2 text-right font-mono text-xs">{formatCount(ion.intensity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function ionLabel(ion: BuMatchedIon): string {
  return `${ion.ion_type}${ion.position}${ion.charge > 1 ? `^${ion.charge}+` : ""}`;
}
