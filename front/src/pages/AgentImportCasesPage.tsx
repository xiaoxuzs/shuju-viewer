import { useQuery } from "@tanstack/react-query";
import { Bot, ChevronRight } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { PageLoading } from "@/components/common/page-loading";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchAgentImportCases } from "@/features/agent-import/api";
import { TransitionLink, usePageTransitionReady } from "@/features/page-transition";

const TERMINAL_STATUSES = new Set(["SUCCESS", "FAILED", "STOPPED"]);

function statusVariant(status: string): "default" | "outline" | "secondary" | "success" | "destructive" {
  if (status === "SUCCESS") return "success";
  if (status === "FAILED" || status === "STOPPED") return "destructive";
  if (status === "READY_FOR_REVIEW" || status === "NEEDS_USER") return "default";
  return "secondary";
}

export function AgentImportCasesPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agent-import-cases"],
    queryFn: fetchAgentImportCases,
    refetchInterval: (query) => {
      const cases = query.state.data;
      return cases?.some((item) => !TERMINAL_STATUSES.has(item.status)) ? 1_500 : false;
    },
  });
  usePageTransitionReady(!isLoading);

  return (
    <>
      <PageHeader
        title="Agent import cases"
        description="Track unknown-format analysis, inspect the generated .zp candidate, and approve it before dataset registration."
        crumbs={[{ label: "Datasets", to: "/datasets" }, { label: "Agent cases" }]}
      />

      {isLoading && <PageLoading />}
      {error && !data && (
        <Card><CardContent className="p-6 text-sm text-destructive">Failed to load Agent import cases.</CardContent></Card>
      )}
      {data?.length === 0 && (
        <Card><CardContent className="p-10 text-center text-sm text-muted-foreground">No Agent import cases yet.</CardContent></Card>
      )}
      {data && data.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((item) => (
            <TransitionLink key={item.case_id} to={`/agent-import-cases/${item.case_id}`} className="group">
              <Card className="h-full border-border/60 transition-colors hover:border-primary/40">
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Bot className="h-5 w-5 text-primary" />
                      <Badge variant={statusVariant(item.status)}>{item.status.replaceAll("_", " ")}</Badge>
                    </div>
                    <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-1" />
                  </div>
                  <CardTitle className="pt-2 text-lg">{item.source_profile}</CardTitle>
                  <CardDescription>{item.analysis_category.replaceAll("_", " ")}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs text-muted-foreground">
                  <div className="font-mono">{item.case_id}</div>
                  <div>Attempts: {item.autonomous_attempt_used} autonomous / {item.guided_attempt_no} guided</div>
                  <div>Updated: {new Date(item.updated_at).toLocaleString()}</div>
                </CardContent>
              </Card>
            </TransitionLink>
          ))}
        </div>
      )}
    </>
  );
}
