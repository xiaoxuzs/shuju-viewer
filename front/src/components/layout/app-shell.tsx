/**
 * 全局壳层：顶栏导航 + `<Outlet />` 渲染子路由。
 * 进入具体数据集后，根据当前路由中的 `slug` 显示第二级导航链接。
 */
import { NavLink, Outlet, useParams } from "react-router-dom";
import { Database, FlaskConical, Microscope } from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/features/theme/ThemeToggle";

export function AppShell() {
  const { slug } = useParams();

  return (
    <div className="relative min-h-screen bg-background">
      <div className="pointer-events-none fixed inset-0 bg-soft-glow opacity-80" />
      <div className="pointer-events-none fixed inset-0 bg-grid opacity-40 [mask-image:radial-gradient(ellipse_at_top,black,transparent_65%)]" />

      <header className="sticky top-0 z-40 flex h-14 items-center border-b border-border/70 bg-background/85 px-6 backdrop-blur">
        <NavLink to="/" className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <Microscope className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight">proteo-viewer</div>
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
              Proteomics
            </div>
          </div>
        </NavLink>

        <nav className="ml-10 flex items-center gap-1 text-sm">
          <HeaderLink to="/datasets" icon={<Database className="h-4 w-4" />}>
            Datasets
          </HeaderLink>
          {slug && (
            <HeaderLink to={`/datasets/${slug}`} icon={<FlaskConical className="h-4 w-4" />}>
              {slug}
            </HeaderLink>
          )}
        </nav>

        <div className="ml-auto pl-4">
          <ThemeToggle />
        </div>
      </header>

      <main className="relative mx-auto max-w-[1600px] px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}

function HeaderLink({
  to,
  children,
  icon,
}: {
  to: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2 rounded-md px-3 py-1.5 text-muted-foreground transition",
          "hover:bg-accent hover:text-foreground",
          isActive && "bg-accent text-foreground",
        )
      }
    >
      {icon}
      <span className="truncate max-w-[260px]">{children}</span>
    </NavLink>
  );
}
