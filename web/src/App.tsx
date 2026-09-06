import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import {
  Routes,
  Route,
  NavLink,
  Navigate,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  Activity,
  BarChart3,
  BookOpen,
  Clock,
  Code,
  Cpu,
  Database,
  CreditCard,
  Eye,
  FolderOpen,
  FileText,
  Globe,
  Heart,
  KeyRound,
  Menu,
  MessageSquare,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Puzzle,
  Radio,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Star,
  Terminal,
  Users,
  GraduationCap,
  Layers,
  Archive,
  CalendarDays,
  Webhook,
  Wrench,
  X,
  Zap,
  Video,
  PenLine,
  Lock,
  ScrollText,
  Receipt,
  Contact,
  Mail,
  Network,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { SelectionSwitcher } from "@nous-research/ui/ui/components/selection-switcher";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { cn } from "@/lib/utils";
import { Backdrop } from "@/components/Backdrop";
import { SidebarFooter } from "@/components/SidebarFooter";
import { SidebarStatusStrip, gatewayLine } from "@/components/SidebarStatusStrip";
import { useBelowBreakpoint } from "@nous-research/ui/hooks/use-below-breakpoint";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import { AuthWidget } from "@/components/AuthWidget";
import { OnboardingWizard } from "@/components/OnboardingWizard";
import AssistantChatPage from "@/pages/AssistantChatPage";
import { PageHeaderProvider } from "@/contexts/PageHeaderProvider";
import { ProfileProvider } from "@/contexts/ProfileProvider";
import { useProfileScope } from "@/contexts/useProfileScope";
import { ProfileSwitcher } from "@/components/ProfileSwitcher";
import { ProfileScopeBanner } from "@/components/ProfileScopeBanner";
import { useSystemActions } from "@/contexts/useSystemActions";
import type { SystemAction } from "@/contexts/system-actions-context";
import ConfigPage from "@/pages/ConfigPage";
import EnvPage from "@/pages/EnvPage";
import FilesPage from "@/pages/FilesPage";
import SessionsPage from "@/pages/SessionsPage";
import LogsPage from "@/pages/LogsPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import ModelsPage from "@/pages/ModelsPage";
import CronPage from "@/pages/CronPage";
import ProfilesPage from "@/pages/ProfilesPage";
import ProfileBuilderPage from "@/pages/ProfileBuilderPage";
import SkillsPage from "@/pages/SkillsPage";
import PluginsPage from "@/pages/PluginsPage";
import McpPage from "@/pages/McpPage";
import PairingPage from "@/pages/PairingPage";
import ChannelsPage from "@/pages/ChannelsPage";
import WebhooksPage from "@/pages/WebhooksPage";
import SystemPage from "@/pages/SystemPage";
import ChatPage from "@/pages/ChatPage";
// VIGIL × WinnyWoo product pages (added on top of the agent runtime)
import MeetingRoomPage from "@/pages/MeetingRoomPage";
import StudioPage from "@/pages/StudioPage";
import OpsTeamPage from "@/pages/OpsTeamPage";
import ConnectionsPage from "@/pages/ConnectionsPage";
import ApprovalsPage from "@/pages/ApprovalsPage";
import BillingPage from "@/pages/BillingPage";
import VaultPage from "@/pages/VaultPage";
import FinancePage from "@/pages/FinancePage";
import CrmPage from "@/pages/CrmPage";
import MailPage from "@/pages/MailPage";
import AuditPage from "@/pages/AuditPage";
import LearnCalendarPage from "@/pages/LearnCalendarPage";
import NoyauPage from "@/pages/NoyauPage";
import LearnDashboardPage from "@/pages/LearnDashboardPage";
import LearnFormationsPage from "@/pages/LearnFormationsPage";
import LearnEmargementPage from "@/pages/LearnEmargementPage";
import LearnVaultPage from "@/pages/LearnVaultPage";
import LearnPeoplePage from "@/pages/LearnPeoplePage";
import { useLearnRole } from "@/lib/supabase";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { useI18n } from "@/i18n";
import type { Translations } from "@/i18n/types";
import { PluginPage, PluginSlot, usePlugins } from "@/plugins";
import type { PluginManifest } from "@/plugins";
import { useTheme } from "@/themes";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";
import { api } from "@/lib/api";
import type { StatusResponse } from "@/lib/api";

/** Où atterrit quelqu'un qui n'a rien demandé de précis — ou qui a demandé une page
 *  que son rôle ne lui ouvre pas.
 *
 *  Le tableau de bord Formation, pas la salle de réunion : c'est la page que tous les
 *  rôles peuvent voir, et c'est le métier. Se retrouver dans une salle de visioconférence
 *  après un refus d'accès ne dit rien d'utile à qui vient de taper /finance. */
function RootRedirect() {
  return <Navigate to="/learn" replace />;
}

function UnknownRouteFallback({ pluginsLoading }: { pluginsLoading: boolean }) {
  if (pluginsLoading) {
    // Render nothing during the plugin-load window — a spinner here would just flash.
    return null;
  }
  return <Navigate to="/learn" replace />;
}

// L'assistant garde le nom VIGIL : c'est l'agent, pas l'application. VTLVS est le
// produit, et la distinction tient quand la plateforme est revendue — seul AGENTS.md
// adopte la marque du nouvel organisme.
const CHAT_NAV_ITEM: NavItem = {
  path: "/chat",
  label: "Vigil",
  icon: Terminal,
  group: "workspace",
};

/**
 * Built-in routes except /chat.  Chat is rendered persistently (outside
 * <Routes>) when embedded — see the persistent chat host block rendered
 * inline near the bottom of this file — so the PTY child, WebSocket,
 * and xterm instance survive when the user visits another tab and comes
 * back.  A `display:none` toggle hides the terminal without unmounting.
 * Routing still owns the URL so /chat deep-links, browser back/forward,
 * and nav highlight keep working.
 */
const BUILTIN_ROUTES_CORE: Record<string, ComponentType> = {
  "/": RootRedirect,
  "/sessions": SessionsPage,
  // VIGIL workspace
  "/ops-team": OpsTeamPage,
  "/connections": ConnectionsPage,
  "/approvals": ApprovalsPage,
  "/meeting-room": MeetingRoomPage,
  "/studio": StudioPage,
  "/vault": VaultPage,
  "/finance": FinancePage,
  "/crm": CrmPage,
  "/mail": MailPage,
  // LEARN — training platform (AZZ&CO)
  "/noyau": NoyauPage,
  "/learn": LearnDashboardPage,
  "/learn/calendar": LearnCalendarPage,
  "/learn/formations": LearnFormationsPage,
  "/learn/emargement": LearnEmargementPage,
  "/learn/coffre": LearnVaultPage,
  "/learn/comptes": LearnPeoplePage,

  // WinnyWoo workspace
  "/audit": AuditPage,
  "/files": FilesPage,
  "/analytics": AnalyticsPage,
  "/models": ModelsPage,
  "/logs": LogsPage,
  "/cron": CronPage,
  "/skills": SkillsPage,
  "/plugins": PluginsPage,
  "/mcp": McpPage,
  "/pairing": PairingPage,
  "/channels": ChannelsPage,
  "/webhooks": WebhooksPage,
  "/system": SystemPage,
  "/profiles": ProfilesPage,
  "/profiles/new": ProfileBuilderPage,
  "/config": ConfigPage,
  "/env": EnvPage,
  "/billing": BillingPage,
};

// Route placeholder for /chat.  The persistent ChatPage host (rendered
// outside <Routes> when embedded chat is on) paints on top; this empty
// element just claims the path so the `*` catch-all redirect doesn't
// fire when the user navigates to /chat.
function ChatRouteSink() {
  return null;
}

const BUILTIN_NAV_REST: NavItem[] = [
  {
    path: "/sessions",
    label: "Sessions Vigil",
    icon: MessageSquare,
    group: "workspace",
  },
  // ── Workspace ──
  { path: "/ops-team", label: "Équipe agentique", icon: Network, group: "workspace" },
  { path: "/connections", label: "Connexions", icon: Plug, group: "workspace" },
  { path: "/approvals", label: "Validations", icon: ShieldCheck, group: "workspace" },
  { path: "/meeting-room", label: "Salle de réunion", icon: Video, group: "workspace" },
  { path: "/studio", label: "Studio", icon: PenLine, group: "workspace" },
  { path: "/vault", label: "Artéfacts", icon: Lock, group: "workspace" },
  // ── Company ──
  { path: "/learn", label: "Formation", icon: GraduationCap, group: "learn" },
  { path: "/learn/calendar", label: "Calendrier", icon: CalendarDays, group: "learn" },
  { path: "/learn/formations", label: "Formations", icon: Layers, group: "learn" },
  { path: "/learn/emargement", label: "Émargement", icon: PenLine, group: "learn" },
  { path: "/learn/coffre", label: "Coffre", icon: Archive, group: "learn" },
  { path: "/learn/comptes", label: "Comptes", icon: Users, group: "learn" },

  { path: "/finance", label: "Finance", icon: Receipt, group: "company", roles: ["super_admin"] },
  { path: "/crm", label: "CRM", icon: Contact, group: "company", roles: ["super_admin", "admin"] },
  { path: "/mail", label: "Mail", icon: Mail, group: "company", roles: ["super_admin", "admin"] },
  // ── Trade desk ──
  // ── Insight ──
  { path: "/audit", label: "Audit", icon: ScrollText, group: "insight", roles: ["super_admin", "auditeur"] },
  { path: "/files", label: "Fichiers", icon: FolderOpen, group: "insight", roles: ["super_admin"] },
  { path: "/analytics", labelKey: "analytics", label: "Analytics", icon: BarChart3, group: "insight", roles: ["super_admin", "admin"] },
  { path: "/models", labelKey: "models", label: "Models", icon: Cpu, group: "insight", roles: ["super_admin", "admin"] },
  { path: "/logs", labelKey: "logs", label: "Logs", icon: FileText, group: "insight", roles: ["super_admin"] },
  // ── System ──
  { path: "/cron", labelKey: "cron", label: "Cron", icon: Clock, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/skills", labelKey: "skills", label: "Skills", icon: Package, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/plugins", labelKey: "plugins", label: "Plugins", icon: Puzzle, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/mcp", label: "MCP", icon: Plug, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/channels", label: "Canaux", icon: Radio, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/webhooks", label: "Webhooks", icon: Webhook, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/pairing", label: "Appairage", icon: ShieldCheck, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/profiles", labelKey: "profiles", label: "Profils agent", icon: Users, group: "system", roles: ["super_admin", "admin"] },
  { path: "/config", labelKey: "config", label: "Config", icon: Settings, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/env", labelKey: "keys", label: "Keys", icon: KeyRound, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/billing", label: "Facturation", icon: CreditCard, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/system", label: "Système", icon: Wrench, group: "system" , roles: ["super_admin", "admin"] },
  { path: "/noyau", label: "Le Noyau", icon: BookOpen, group: "system", roles: ["super_admin", "admin"] },
];

// Sidebar section ordering + labels. Grouping the ~30 destinations into five
// labelled sections keeps the nav scannable instead of one long confusing list.
type NavGroupKey = "workspace" | "learn" | "company" | "insight" | "system";
const NAV_GROUP_ORDER: NavGroupKey[] = ["workspace", "learn", "company", "insight", "system"];
const NAV_GROUP_LABEL: Record<NavGroupKey, string> = {
  workspace: "Espace de travail",
  learn: "Formation",
  company: "Organisme",
  insight: "Pilotage",
  system: "Administration",
};

const ICON_MAP: Record<string, ComponentType<{ className?: string }>> = {
  Activity,
  BarChart3,
  Clock,
  Cpu,
  FileText,
  FolderOpen,
  KeyRound,
  MessageSquare,
  Package,
  Settings,
  Puzzle,
  Sparkles,
  Terminal,
  Globe,
  Database,
  Shield,
  Users,
  Wrench,
  Zap,
  Heart,
  Star,
  Code,
  Eye,
};

function resolveIcon(name: string): ComponentType<{ className?: string }> {
  return ICON_MAP[name] ?? Puzzle;
}

function buildNavItems(
  builtIn: NavItem[],
  manifests: PluginManifest[],
): NavItem[] {
  const items = [...builtIn];

  for (const manifest of manifests) {
    if (manifest.tab.override) continue;
    if (manifest.tab.hidden) continue;

    const pluginItem: NavItem = {
      path: manifest.tab.path,
      label: manifest.label,
      icon: resolveIcon(manifest.icon),
    };

    const pos = manifest.tab.position ?? "end";
    if (pos === "end") {
      items.push(pluginItem);
    } else if (pos.startsWith("after:")) {
      const target = "/" + pos.slice(6);
      const idx = items.findIndex((i) => i.path === target);
      items.splice(idx >= 0 ? idx + 1 : items.length, 0, pluginItem);
    } else if (pos.startsWith("before:")) {
      const target = "/" + pos.slice(7);
      const idx = items.findIndex((i) => i.path === target);
      items.splice(idx >= 0 ? idx : items.length, 0, pluginItem);
    } else {
      items.push(pluginItem);
    }
  }

  return items;
}

/** Split merged nav into built-in sidebar entries vs plugin tabs, preserving plugin order hints. */
function partitionSidebarNav(
  builtIn: NavItem[],
  manifests: PluginManifest[],
): { coreItems: NavItem[]; pluginItems: NavItem[] } {
  const merged = buildNavItems(builtIn, manifests);
  const builtinPaths = new Set(builtIn.map((i) => i.path));
  const coreItems: NavItem[] = [];
  const pluginItems: NavItem[] = [];
  for (const item of merged) {
    if (builtinPaths.has(item.path)) coreItems.push(item);
    else pluginItems.push(item);
  }
  return { coreItems, pluginItems };
}

function buildRoutes(
  builtinRoutes: Record<string, ComponentType>,
  manifests: PluginManifest[],
): Array<{
  key: string;
  path: string;
  element: ReactNode;
}> {
  const byOverride = new Map<string, PluginManifest>();
  const addons: PluginManifest[] = [];

  for (const m of manifests) {
    if (m.tab.override) {
      byOverride.set(m.tab.override, m);
    } else {
      addons.push(m);
    }
  }

  const routes: Array<{
    key: string;
    path: string;
    element: ReactNode;
  }> = [];

  for (const [path, Component] of Object.entries(builtinRoutes)) {
    const om = byOverride.get(path);
    if (om) {
      routes.push({
        key: `override:${om.name}`,
        path,
        element: <PluginPage name={om.name} />,
      });
    } else {
      routes.push({ key: `builtin:${path}`, path, element: <Component /> });
    }
  }

  for (const m of addons) {
    if (m.tab.hidden) continue;
    if (m.tab.path === "/plugins") continue;
    if (builtinRoutes[m.tab.path]) continue;
    routes.push({
      key: `plugin:${m.name}`,
      path: m.tab.path,
      element: <PluginPage name={m.name} />,
    });
  }

  for (const m of manifests) {
    if (!m.tab.hidden) continue;
    if (m.tab.path === "/plugins") continue;
    if (builtinRoutes[m.tab.path] || m.tab.override) continue;
    routes.push({
      key: `plugin:hidden:${m.name}`,
      path: m.tab.path,
      element: <PluginPage name={m.name} />,
    });
  }

  return routes;
}

const SIDEBAR_COLLAPSED_KEY = "hermes-sidebar-collapsed";

export default function App() {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const { manifests, loading: pluginsLoading } = usePlugins();
  const { theme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });
  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      } catch { /* localStorage may be unavailable in private browsing */ }
      return next;
    });
  }, []);
  const isMobile = useBelowBreakpoint(1024);
  const isDesktopCollapsed = collapsed && !isMobile;
  const tooltipWarmRef = useRef(0);
  const sidebarStatus = useSidebarStatus();
  const isDocsRoute = pathname === "/docs" || pathname === "/docs/";
  const normalizedPath = pathname.replace(/\/$/, "") || "/";
  const isChatRoute = normalizedPath === "/chat";
  const embeddedChat = isDashboardEmbeddedChatEnabled();

  // `dashboard.show_token_analytics` gates the Analytics nav item.  The
  // page itself remains reachable by URL (it renders an explanation when
  // the flag is off — see AnalyticsPage), but hiding the nav entry avoids
  // surfacing misleading token/cost numbers in the sidebar.  Default off.
  const [showTokenAnalytics, setShowTokenAnalytics] = useState(false);
  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        const dash = (cfg?.dashboard ?? {}) as {
          show_token_analytics?: unknown;
        };
        setShowTokenAnalytics(dash.show_token_analytics === true);
      })
      .catch(() => setShowTokenAnalytics(false));
  }, []);

  // A plugin can replace the built-in /chat page via `tab.override: "/chat"`
  // in its manifest.  When one does, `buildRoutes` already swaps the route
  // element for <PluginPage /> — but we also have to suppress the
  // persistent ChatPage host below, or the plugin's page and the built-in
  // terminal would paint on top of each other.  The override is niche
  // (nothing ships overriding /chat today) but it's an advertised
  // extension point, so preserve the pre-persistence contract: when a
  // plugin owns /chat, the built-in chat UI is entirely absent.
  //
  // Waiting on `pluginsLoading` is load-bearing: manifests arrive
  // asynchronously from /api/dashboard/plugins, so on initial render
  // `chatOverriddenByPlugin` is always false.  Without the loading
  // gate, the persistent host would mount, spawn a PTY, and THEN get
  // yanked out from under the user when the plugin's manifest resolves
  // — killing the session mid-paint.  Delaying host mount by the
  // plugin-load window (typically <50ms, worst case 2s safety timeout)
  // is the cheaper trade-off.
  // Drives which nav entries appear and which routes resolve. Null while the session
  // loads and for signed-out users, so gated entries stay hidden until a role is known —
  // failing closed rather than flashing a link that then disappears.
  const learnRole = useLearnRole();

  const chatOverriddenByPlugin = useMemo(
    () => manifests.some((m) => m.tab.override === "/chat"),
    [manifests],
  );

  const builtinRoutes = useMemo(
    () => ({
      ...BUILTIN_ROUTES_CORE,
      // Hiding a link stops nobody who can type a URL. Logs and Files expose operational
      // traces and raw stored objects across the platform, so the route resolves to a
      // redirect for anyone below super_admin — and the gateway refuses them regardless.
      // Hidden links stop nobody who can type a URL, so each gated path resolves to a
      // redirect for anyone outside its allowlist. The gateway refuses them regardless;
      // this is what stops the page rendering an empty shell before that refusal lands.
      ...Object.fromEntries(
        BUILTIN_NAV_REST.filter(
          (n) => n.roles && !(learnRole && n.roles.includes(learnRole)),
        ).map((n) => [n.path, RootRedirect]),
      ),
      // Embedded TUI (PTY over WS) when the dashboard serves it; otherwise the
      // gateway-backed VIGIL assistant (HTTP SSE) — the only chat that works
      // through the Vercel product.
      "/chat": embeddedChat ? ChatRouteSink : AssistantChatPage,
    }),
    [embeddedChat, learnRole],
  );

  const builtinNav = useMemo(() => {
    // Chat is always in the nav now: the embedded TUI when the dashboard serves
    // it, otherwise the gateway-backed VIGIL assistant.
    const base = [CHAT_NAV_ITEM, ...BUILTIN_NAV_REST];
    const visible = base.filter((n) => !n.roles || (learnRole && n.roles.includes(learnRole)));
    return showTokenAnalytics
      ? visible
      : visible.filter((n) => n.path !== "/analytics");
  }, [showTokenAnalytics, learnRole]);

  const sidebarNav = useMemo(
    () => partitionSidebarNav(builtinNav, manifests),
    [builtinNav, manifests],
  );
  const routes = useMemo(
    () => buildRoutes(builtinRoutes, manifests),
    [builtinRoutes, manifests],
  );
  // Le titre de page se déduisait du chemin, faute de mieux : « /learn » donnait « Learn »
  // et « /learn/calendar » donnait « Learn/calendar ». La barre latérale connaît déjà le
  // nom de chaque destination — on le lui demande, plutôt que d'entretenir une deuxième
  // liste qui dérive. Les onglets de plugins gardent la priorité : ils sont plus
  // spécifiques que la navigation intégrée.
  const pageTitleSources = useMemo(
    () => [
      ...manifests
        .filter((m) => !m.tab.hidden)
        .map((m) => ({
          path: m.tab.override ?? m.tab.path,
          label: m.label,
        })),
      ...builtinNav.map((n) => ({ path: n.path, label: n.label })),
    ],
    [manifests, builtinNav],
  );


  const layoutVariant = theme.layoutVariant ?? "standard";

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [mobileOpen]);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1024px)");
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) setMobileOpen(false);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return (
    <ProfileProvider>
    <div
      data-layout-variant={layoutVariant}
      className="flex h-dvh max-h-dvh min-h-0 flex-col overflow-hidden bg-background text-text-primary antialiased"
    >
      <SelectionSwitcher />
      <Backdrop />
      <PluginSlot name="backdrop" />

      <header
        className={cn(
          "lg:hidden fixed top-0 left-0 right-0 z-40 min-h-14",
          "flex items-center gap-2 px-4 py-2",
          "border-b border-current/20",
          "bg-background-base/90 backdrop-blur-sm",
        )}
        style={{
          background: "var(--component-header-background)",
          borderImage: "var(--component-header-border-image)",
          clipPath: "var(--component-header-clip-path)",
        }}
      >
        <Button
          ghost
          size="icon"
          onClick={() => setMobileOpen(true)}
          aria-label={t.app.openNavigation}
          aria-expanded={mobileOpen}
          aria-controls="app-sidebar"
          className="text-text-secondary hover:text-midground"
        >
          <Menu />
        </Button>

        <Typography
          className="font-bold text-[0.95rem] leading-[0.95] tracking-[0.05em] text-midground"
        >
          {t.app.brand}
        </Typography>
      </header>

      {mobileOpen && (
        <Button
          ghost
          aria-label={t.app.closeNavigation}
          onClick={closeMobile}
          className={cn(
            "lg:hidden fixed inset-0 z-40 p-0 block",
            "bg-[color-mix(in_srgb,var(--midground-base)_45%,transparent)] backdrop-blur-sm",
          )}
        />
      )}

      <PluginSlot name="header-banner" />
      <ProfileScopeBanner />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden pt-14 lg:pt-0">
        <div className="flex min-h-0 min-w-0 flex-1">
          <aside
            id="app-sidebar"
            aria-label={t.app.navigation}
            className={cn(
              "fixed top-0 left-0 z-50 flex h-dvh max-h-dvh w-64 min-h-0 flex-col",
              "border-r border-current/20",
              "bg-background-base/95 backdrop-blur-sm",
              "transition-[transform] duration-200 ease-out",
              mobileOpen ? "translate-x-0" : "-translate-x-full",
              "lg:sticky lg:top-0 lg:translate-x-0 lg:shrink-0 lg:overflow-hidden",
              "lg:transition-[width] lg:duration-[600ms] lg:ease-[cubic-bezier(0.33,1.35,0.62,1)]",
              collapsed && "lg:w-14",
            )}
            style={{
              background: "var(--component-sidebar-background)",
              clipPath: "var(--component-sidebar-clip-path)",
              borderImage: "var(--component-sidebar-border-image)",
            }}
          >
            <div
              className={cn(
                "flex h-14 shrink-0 items-center gap-2",
                "border-b border-current/20",
                collapsed ? "lg:justify-center lg:px-0" : "px-4 justify-between",
              )}
            >
              <div
                className={cn(
                  "flex items-center gap-2",
                  collapsed && "lg:hidden",
                )}
              >
                <PluginSlot name="header-left" />

                {/* La marque de l'application est VTLVS ; VIGIL est le nom de
                    l'assistant, et il le reste — ils ne désignent pas la même chose. */}
                <img
                  src="/logo-mark.png"
                  alt="VTLVS"
                  height={28}
                  className="h-7 w-auto shrink-0"
                />
                <Typography className="font-bold text-[1.05rem] leading-[0.95] tracking-[0.045rem]">
                  <span>VTLVS</span>
                  <br />
                  <span className="text-[0.72rem] font-medium uppercase tracking-[0.14em] opacity-60">
                    Plateforme de formation
                  </span>
                </Typography>
              </div>

              <Button
                ghost
                size="icon"
                onClick={closeMobile}
                aria-label={t.app.closeNavigation}
                className="lg:hidden text-text-secondary hover:text-midground"
              >
                <X />
              </Button>

              <Button
                ghost
                size="icon"
                onClick={toggleCollapsed}
                aria-label={
                  collapsed ? t.common.expand : t.common.collapse
                }
                className="hidden lg:flex text-text-secondary hover:text-midground"
              >
                {collapsed ? (
                  <PanelLeftOpen className="h-4 w-4" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" />
                )}
              </Button>
            </div>

            <ProfileSwitcher collapsed={isDesktopCollapsed} />

            <nav
              className="min-h-0 w-full flex-1 overflow-y-auto overflow-x-hidden border-t border-current/10 py-2"
              aria-label={t.app.navigation}
            >
              {NAV_GROUP_ORDER.map((groupKey) => {
                const groupItems = sidebarNav.coreItems.filter(
                  (it) => (it.group ?? "system") === groupKey,
                );
                if (groupItems.length === 0) return null;
                return (
                  <div key={groupKey} role="group" aria-label={NAV_GROUP_LABEL[groupKey]} className="flex flex-col">
                    <span
                      className={cn(
                        "px-5 pt-3 pb-1",
                        "font-mondwest text-display text-[0.7rem] uppercase tracking-[0.14em] text-text-tertiary",
                        isDesktopCollapsed && "lg:hidden",
                      )}
                    >
                      {NAV_GROUP_LABEL[groupKey]}
                    </span>
                    <ul className="flex flex-col">
                      {groupItems.map((item) => (
                        <SidebarNavLink
                          closeMobile={closeMobile}
                          collapsed={isDesktopCollapsed}
                          item={item}
                          key={item.path}
                          t={t}
                          tooltipWarmRef={tooltipWarmRef}
                        />
                      ))}
                    </ul>
                  </div>
                );
              })}

              {sidebarNav.pluginItems.length > 0 && (
                <div
                  aria-labelledby="hermes-sidebar-plugin-nav-heading"
                  className="flex flex-col border-t border-current/10 pb-2"
                  role="group"
                >
                  <span
                    className={cn(
                      "px-5 pt-2.5 pb-1",
                      "font-mondwest text-display text-xs tracking-[0.12em] text-text-tertiary",
                      isDesktopCollapsed && "lg:hidden",
                    )}
                    id="hermes-sidebar-plugin-nav-heading"
                  >
                    {t.app.pluginNavSection}
                  </span>

                  <ul className="flex flex-col">
                    {sidebarNav.pluginItems.map((item) => (
                      <SidebarNavLink
                        closeMobile={closeMobile}
                        collapsed={isDesktopCollapsed}
                        item={item}
                        key={item.path}
                        t={t}
                        tooltipWarmRef={tooltipWarmRef}
                      />
                    ))}
                  </ul>
                </div>
              )}
            </nav>

            <SidebarSystemActions
              collapsed={isDesktopCollapsed}
              onNavigate={closeMobile}
              status={sidebarStatus}
              tooltipWarmRef={tooltipWarmRef}
            />

            <div
              className={cn(
                "flex shrink-0 items-center gap-2",
                "px-3 py-2",
                "border-t border-current/20",
                isDesktopCollapsed
                  ? "lg:flex-col lg:items-start lg:gap-3 lg:py-3"
                  : "justify-between",
              )}
            >
              <div
                className={cn(
                  "flex min-w-0 items-center gap-2",
                  isDesktopCollapsed && "lg:flex-col lg:items-start",
                )}
              >
                <PluginSlot name="header-right" />

                <SidebarIconWithTooltip
                  collapsed={isDesktopCollapsed}
                  label={t.theme?.switchTheme ?? "Switch theme"}
                  tooltipWarmRef={tooltipWarmRef}
                >
                  <ThemeSwitcher collapsed={isDesktopCollapsed} dropUp />
                </SidebarIconWithTooltip>

                <SidebarIconWithTooltip
                  collapsed={isDesktopCollapsed}
                  label={t.language.switchTo}
                  tooltipWarmRef={tooltipWarmRef}
                >
                  <LanguageSwitcher collapsed={isDesktopCollapsed} dropUp />
                </SidebarIconWithTooltip>
              </div>
            </div>

            <div
              className={cn(
                "flex shrink-0 flex-col",
                isDesktopCollapsed && "lg:hidden",
              )}
            >
              <AuthWidget />
              <SidebarFooter status={sidebarStatus} />
            </div>
          </aside>

          <PageHeaderProvider pluginTabs={pageTitleSources}>
            <div
              className={cn(
                "relative z-2 flex min-w-0 min-h-0 flex-1 flex-col",
                "px-3 sm:px-6",
                // Clear the fixed mobile top bar (the <header> is lg:hidden,
                // fixed top-0, z-40, min-h-14 ≈ 56px). Without this, the bar
                // overlays the top of every page on < lg widths — which was
                // hiding the meeting-room action buttons ("Bring in AI" /
                // "Start live meeting") beneath the nav. Restore the tight
                // padding at lg where the bar is gone.
                isChatRoute
                  ? "pb-0 pt-16 lg:pt-4"
                  : "pt-16 lg:pt-6",
                isDocsRoute && "min-h-0 flex-1",
              )}
            >
              <PluginSlot name="pre-main" />
              <div
                className={cn(
                  "w-full min-w-0",
                  !isChatRoute &&
                    "pb-[calc(2rem+env(safe-area-inset-bottom,0px))] lg:pb-8",
                  (isDocsRoute || isChatRoute) &&
                    "min-h-0 flex flex-1 flex-col",
                )}
              >
                <ProfileKeyedRoutes>
                  {/* key re-triggers the enter animation per navigation (delight.css) */}
                  <div key={pathname} className="vigil-page-enter min-h-0 min-w-0 flex-1 flex flex-col">
                  <Routes>
                    {routes.map(({ key, path, element }) => (
                      <Route key={key} path={path} element={element} />
                    ))}
                    <Route
                      path="*"
                      element={
                        <UnknownRouteFallback pluginsLoading={pluginsLoading} />
                      }
                    />
                  </Routes>
                  </div>
                </ProfileKeyedRoutes>

                {embeddedChat &&
                  !chatOverriddenByPlugin &&
                  (pluginsLoading ? (
                    isChatRoute ? (
                      <div
                        className="flex min-h-0 min-w-0 flex-1 items-center justify-center"
                        aria-busy="true"
                        aria-live="polite"
                      >
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Spinner />
                          <span>Loading chat…</span>
                        </div>
                      </div>
                    ) : null
                  ) : (
                    <div
                      data-chat-active={isChatRoute ? "true" : "false"}
                      className={cn(
                        "min-h-0 min-w-0",
                        isChatRoute ? "flex flex-1 flex-col" : "hidden",
                      )}
                      aria-hidden={!isChatRoute}
                    >
                      <ChatPage isActive={isChatRoute} />
                    </div>
                  ))}
              </div>
              <PluginSlot name="post-main" />
            </div>
          </PageHeaderProvider>
        </div>
      </div>

      <PluginSlot name="overlay" />
      <OnboardingWizard />
    </div>
    </ProfileProvider>
  );
}

/**
 * Remounts the entire routed page tree when the global management profile
 * changes. Pages load their data on mount; without this, a page opened
 * under profile A would keep showing A's state while writes (via the
 * fetchJSON ?profile= injection) silently targeted the newly selected
 * profile B — the exact stale-target footgun the switcher exists to kill.
 * Keying by profile resets every page's local state so it refetches under
 * the new scope. The persistent ChatPage host below handles its own
 * remount (channel keyed on scopedProfile).
 */
function ProfileKeyedRoutes({ children }: { children: ReactNode }) {
  const { profile } = useProfileScope();
  return <div key={profile || "__own__"} className="contents">{children}</div>;
}

function SidebarNavLink({
  closeMobile,
  collapsed,
  item,
  tooltipWarmRef,
  t,
}: SidebarNavLinkProps) {
  const { path, label, labelKey, icon: Icon } = item;
  const liRef = useRef<HTMLLIElement>(null);
  const [hovered, setHovered] = useState(false);

  const navLabel = labelKey
    ? ((t.app.nav as Record<string, string>)[labelKey] ?? label)
    : label;

  return (
    <li
      ref={liRef}
      onMouseEnter={collapsed ? () => setHovered(true) : undefined}
      onMouseLeave={collapsed ? () => setHovered(false) : undefined}
    >
      <NavLink
        to={path}
        end={path === "/sessions"}
        onClick={closeMobile}
        aria-label={collapsed ? navLabel : undefined}
        onFocus={collapsed ? () => setHovered(true) : undefined}
        onBlur={collapsed ? () => setHovered(false) : undefined}
        className={({ isActive }) =>
          cn(
            "group/nav relative flex items-center gap-3",
            "px-5 py-2.5",
            "font-mondwest text-display uppercase text-sm tracking-[0.12em]",
            "whitespace-nowrap transition-colors cursor-pointer",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
            isActive
              ? "text-midground"
              : "text-text-secondary hover:text-midground",
          )
        }
        style={{
          clipPath: "var(--component-tab-clip-path)",
        }}
      >
        {({ isActive }) => (
          <>
            <Icon className="h-3.5 w-3.5 shrink-0" />

            <span
              className={cn(
                "truncate transition-opacity duration-300",
                collapsed ? "lg:opacity-0" : "lg:opacity-100",
              )}
            >
              {navLabel}
            </span>

            <span
              aria-hidden
              className="absolute inset-y-0.5 left-1.5 right-1.5 bg-midground opacity-0 pointer-events-none transition-opacity duration-200 group-hover/nav:opacity-5"
            />

            {isActive && (
              <span
                aria-hidden
                className="absolute left-0 top-0 bottom-0 w-px bg-midground"
              />
            )}
          </>
        )}
      </NavLink>

      {collapsed && hovered && liRef.current && (
        <SidebarTooltip anchor={liRef.current} label={navLabel} warmRef={tooltipWarmRef} />
      )}
    </li>
  );
}

function SidebarSystemActions({
  collapsed,
  onNavigate,
  status,
  tooltipWarmRef,
}: SidebarSystemActionsProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { activeAction, isBusy, isRunning, pendingAction, runAction } =
    useSystemActions();

  // Restarting the gateway and updating VIGIL were dashboard operations: they act on a
  // process the operator runs locally. This deployment's gateway is a managed Railway
  // service — a button that cannot do what it says is worse than no button, and worse
  // still when the thing it claims to restart serves an organisme's live sessions.
  const items: SystemActionItem[] = [];

  const handleClick = (action: SystemAction) => {
    if (isBusy) return;
    void runAction(action);
    navigate("/sessions");
    onNavigate();
  };

  return (
    <div
      className={cn(
        "shrink-0 flex flex-col",
        "border-t border-current/10",
        "py-1",
      )}
    >
      <span
        className={cn(
          "px-5 pt-0.5 pb-0.5",
          "font-mondwest text-display text-xs tracking-[0.12em] text-text-tertiary",
          collapsed && "lg:hidden",
        )}
      >
        {t.app.system}
      </span>

      {/* L'état de la passerelle décrivait un processus local que l'opérateur lançait
          lui-même. Ce déploiement n'en a pas : `/api/status` est répondu par le Worker,
          qui annonce `dashboard: false`. Le voyant affichait donc « Hors ligne » en
          permanence, à côté d'une application qui fonctionne — un indicateur qui ment
          dans un sens rassurant est une nuisance ; dans l'autre, il fait ouvrir un ticket.
          On ne le montre que là où il a un sens. */}
      {status?.dashboard !== false && (
        <>
          <div className={cn(collapsed && "lg:hidden")}>
            <SidebarStatusStrip status={status} />
          </div>
          <GatewayDot collapsed={collapsed} status={status} tooltipWarmRef={tooltipWarmRef} />
        </>
      )}

      <ul className="flex flex-col">
        {items.map((item) => (
          <SystemActionButton
            key={item.action}
            collapsed={collapsed}
            disabled={isBusy && !(pendingAction === item.action || (activeAction === item.action && isRunning))}
            tooltipWarmRef={tooltipWarmRef}
            isPending={pendingAction === item.action}
            isRunning={activeAction === item.action && isRunning && pendingAction !== item.action}
            item={item}
            onClick={() => handleClick(item.action)}
          />
        ))}
      </ul>
    </div>
  );
}

function SystemActionButton({
  collapsed,
  disabled,
  isPending,
  isRunning: isActionRunning,
  item,
  onClick,
  tooltipWarmRef,
}: SystemActionButtonProps) {
  const { icon: Icon, label, runningLabel, spin } = item;
  const liRef = useRef<HTMLLIElement>(null);
  const [hovered, setHovered] = useState(false);
  const busy = isPending || isActionRunning;
  const displayLabel = isActionRunning ? runningLabel : label;

  return (
    <li
      ref={liRef}
      onMouseEnter={collapsed ? () => setHovered(true) : undefined}
      onMouseLeave={collapsed ? () => setHovered(false) : undefined}
    >
      <button
        onClick={onClick}
        disabled={disabled}
        aria-busy={busy}
        aria-label={collapsed ? displayLabel : undefined}
        onFocus={collapsed ? () => setHovered(true) : undefined}
        onBlur={collapsed ? () => setHovered(false) : undefined}
        type="button"
        className={cn(
          "group/action relative flex w-full items-center gap-3",
          "px-5 py-2.5",
          "font-mondwest text-display text-xs tracking-[0.1em]",
          "whitespace-nowrap transition-colors cursor-pointer",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          busy
            ? "text-midground"
            : "text-text-secondary hover:text-midground",
          "disabled:text-text-disabled disabled:cursor-not-allowed",
        )}
      >
        {isPending ? (
          <Spinner className="shrink-0 text-[0.875rem]" />
        ) : isActionRunning && spin ? (
          <Spinner className="shrink-0 text-[0.875rem]" />
        ) : (
          <Icon
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              isActionRunning && !spin && "animate-pulse",
            )}
          />
        )}

        <span className={cn(
          "truncate transition-opacity duration-300",
          collapsed ? "lg:opacity-0" : "lg:opacity-100",
        )}>
          {displayLabel}
        </span>

        <span
          aria-hidden
          className="absolute inset-y-0.5 left-1.5 right-1.5 bg-midground opacity-0 pointer-events-none transition-opacity duration-200 group-hover/action:opacity-5"
        />

        {busy && (
          <span
            aria-hidden
            className="absolute left-0 top-0 bottom-0 w-px bg-midground"
          />
        )}
      </button>

      {collapsed && hovered && liRef.current && (
        <SidebarTooltip anchor={liRef.current} label={displayLabel} warmRef={tooltipWarmRef} />
      )}
    </li>
  );
}

function SidebarIconWithTooltip({
  children,
  collapsed,
  label,
  tooltipWarmRef,
}: SidebarIconWithTooltipProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState(false);

  return (
    <div
      ref={ref}
      className={cn(
        "relative w-fit",
        collapsed && "group/icon",
      )}
      onMouseEnter={collapsed ? () => setHovered(true) : undefined}
      onMouseLeave={collapsed ? () => setHovered(false) : undefined}
    >
      {children}

      {collapsed && (
        <span
          aria-hidden
          className="absolute inset-y-0 inset-x-[-0.375rem] bg-midground opacity-0 pointer-events-none transition-opacity duration-200 group-hover/icon:opacity-5 hidden lg:block"
        />
      )}

      {collapsed && hovered && ref.current && (
        <SidebarTooltip anchor={ref.current} label={label} warmRef={tooltipWarmRef} />
      )}
    </div>
  );
}

function GatewayDot({ collapsed, status, tooltipWarmRef }: GatewayDotProps) {
  const { t } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState(false);

  const toneToColor: Record<string, string> = {
    "text-success": "bg-success",
    "text-warning": "bg-warning",
    "text-destructive": "bg-destructive",
    "text-muted-foreground": "bg-muted-foreground",
  };

  let color: string;
  let label: string;

  if (!status) {
    color = "bg-midground/20";
    label = t.status.gateway;
  } else {
    const gw = gatewayLine(status, t);
    color = toneToColor[gw.tone] ?? "bg-muted-foreground";
    label = `${t.status.gateway} ${gw.label}`;
  }

  return (
    <div
      ref={ref}
      className={cn(
        "hidden lg:flex py-3 pl-[1.625rem] transition-opacity duration-300",
        collapsed ? "lg:opacity-100" : "lg:opacity-0 lg:h-0 lg:py-0 lg:overflow-hidden",
      )}
      role="status"
      aria-label={label}
      tabIndex={collapsed ? 0 : -1}
      onMouseEnter={collapsed ? () => setHovered(true) : undefined}
      onMouseLeave={collapsed ? () => setHovered(false) : undefined}
      onFocus={collapsed ? () => setHovered(true) : undefined}
      onBlur={collapsed ? () => setHovered(false) : undefined}
    >
      <span
        aria-hidden
        className={cn("h-1.5 w-1.5 rounded-full", color)}
      />

      {hovered && ref.current && (
        <SidebarTooltip anchor={ref.current} label={label} warmRef={tooltipWarmRef} />
      )}
    </div>
  );
}

function SidebarTooltip({ anchor, label, warmRef }: SidebarTooltipProps) {
  const rect = anchor.getBoundingClientRect();
  const sidebar = document.getElementById("app-sidebar");
  const sidebarRight = sidebar?.getBoundingClientRect().right ?? rect.right;

  const isWarm = warmRef ? Date.now() - warmRef.current < 300 : false;

  useEffect(() => {
    if (warmRef) warmRef.current = Date.now();
    return () => {
      if (warmRef) warmRef.current = Date.now();
    };
  }, [warmRef]);

  return createPortal(
    <span
      className={cn(
        "fixed z-[100] pointer-events-none",
        "px-2 py-1",
        "bg-background-base/95 border border-current/20 backdrop-blur-sm shadow-lg",
        "font-mondwest text-display text-xs tracking-[0.1em] text-midground uppercase",
      )}
      style={{
        top: rect.top + rect.height / 2,
        left: sidebarRight + 8,
        transform: "translateY(-50%)",
        opacity: isWarm ? 1 : undefined,
        animation: isWarm ? "none" : "sidebar-tooltip-in 120ms ease-out",
      }}
    >
      {label}
    </span>,
    document.body,
  );
}

type TooltipWarmRef = React.RefObject<number>;

interface GatewayDotProps {
  collapsed: boolean;
  status: StatusResponse | null;
  tooltipWarmRef: TooltipWarmRef;
}

interface NavItem {
  icon: ComponentType<{ className?: string }>;
  label: string;
  labelKey?: string;
  path: string;
  group?: NavGroupKey;
  /** Absent means everyone. Present means only these LEARN roles see the entry.
   *  Hiding a link is tidiness, not security — the gateway re-checks every call. */
  roles?: string[];
}

interface SidebarIconWithTooltipProps {
  children: ReactNode;
  collapsed: boolean;
  label: string;
  tooltipWarmRef: TooltipWarmRef;
}

interface SidebarNavLinkProps {
  closeMobile: () => void;
  collapsed: boolean;
  item: NavItem;
  t: Translations;
  tooltipWarmRef: TooltipWarmRef;
}

interface SidebarSystemActionsProps {
  collapsed: boolean;
  onNavigate: () => void;
  status: StatusResponse | null;
  tooltipWarmRef: TooltipWarmRef;
}

interface SidebarTooltipProps {
  anchor: HTMLElement;
  label: string;
  warmRef?: TooltipWarmRef;
}

interface SystemActionButtonProps {
  collapsed: boolean;
  disabled: boolean;
  isPending: boolean;
  isRunning: boolean;
  item: SystemActionItem;
  onClick: () => void;
  tooltipWarmRef: TooltipWarmRef;
}

interface SystemActionItem {
  action: SystemAction;
  icon: ComponentType<{ className?: string }>;
  label: string;
  runningLabel: string;
  spin: boolean;
}
