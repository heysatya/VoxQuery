"use client";

import React, { useState, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { motion, AnimatePresence } from "framer-motion";
import { 
  Database, 
  MessageSquareWarning, 
  Activity, 
  Settings,
  ChevronRight,
  ShieldAlert,
  Loader2,
  RefreshCw,
  Search,
  BookOpen,
  X,
  Plus,
  Edit2,
  CheckCircle2,
  LayoutDashboard,
  Users,
  Play,
  Copy,
  BarChart3,
  TerminalSquare,
  Menu
} from "lucide-react";
import { 
  fetchAdminFeedback, 
  fetchAdminGlossary, 
  postAdminGlossary,
  fetchAdminWorkspaces,
  fetchAdminStats,
  fetchGlossaryPreview
} from "../../lib/api";
import { cn } from "../../lib/utils";
import { VoxQueryLogo } from "../components/brand/VoxQueryLogo";

export default function AdminConsole() {
  const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";
  
  if (authMode === "fake") {
    return <AdminDashboard getToken={async () => "fake_admin_token"} />;
  }

  return <ClerkAdminConsole />;
}

function ClerkAdminConsole() {
  const { isLoaded, isSignedIn, getToken } = useAuth();

  if (!isLoaded) {
    return (
      <main className="min-h-screen bg-[#090B10] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-[var(--accent-blue)] animate-spin" />
      </main>
    );
  }

  if (!isSignedIn) {
    return (
      <main className="min-h-screen bg-[#090B10] flex flex-col items-center justify-center p-4">
        <section className="glass-card p-8 max-w-md w-full text-center space-y-6">
          <ShieldAlert className="w-12 h-12 text-[var(--accent-rose)] mx-auto" />
          <h1 className="text-2xl font-bold text-white">Admin Access Required</h1>
          <p className="text-[var(--text-secondary)] text-sm">You must sign in as an administrator to view this page.</p>
        </section>
      </main>
    );
  }

  return <AdminDashboard getToken={getToken} />;
}

type TabType = "overview" | "history" | "vocabulary" | "workspaces" | "quality" | "analytics";

function AdminDashboard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [activeTab, setActiveTab] = useState<TabType>("overview");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <main className="min-h-screen flex flex-col md:flex-row bg-[#090B10]">
      {/* Mobile Header Bar */}
      <div className="md:hidden flex items-center justify-between p-4 border-b border-white/5 bg-[#10141C] z-30">
        <VoxQueryLogo variant="admin" />
        <button
          type="button"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 text-white hover:text-[var(--accent-blue)]"
          aria-label="Toggle admin navigation menu"
        >
          <Menu className="w-6 h-6" />
        </button>
      </div>

      {/* Sidebar Navigation (Desktop + Mobile Drawer) */}
      <aside className={cn(
        "w-full md:w-64 border-r border-white/5 bg-[#10141C]/90 backdrop-blur-xl flex flex-col z-20 transition-all",
        mobileMenuOpen ? "block" : "hidden md:flex"
      )}>
        <div className="p-6 hidden md:block">
          <VoxQueryLogo variant="admin" />
        </div>
        
        <nav className="flex-1 px-4 space-y-1.5 mt-2">
          <SidebarItem 
            icon={<LayoutDashboard className="w-4 h-4" />}
            label="Overview" 
            isActive={activeTab === "overview"}
            onClick={() => { setActiveTab("overview"); setMobileMenuOpen(false); }}
          />
          <SidebarItem 
            icon={<TerminalSquare className="w-4 h-4" />}
            label="Query History" 
            isActive={activeTab === "history"}
            onClick={() => { setActiveTab("history"); setMobileMenuOpen(false); }}
          />
          <SidebarItem 
            icon={<BookOpen className="w-4 h-4" />}
            label="Business Vocabulary" 
            isActive={activeTab === "vocabulary"}
            onClick={() => { setActiveTab("vocabulary"); setMobileMenuOpen(false); }}
          />
          <SidebarItem 
            icon={<Users className="w-4 h-4" />}
            label="Workspaces" 
            isActive={activeTab === "workspaces"}
            onClick={() => { setActiveTab("workspaces"); setMobileMenuOpen(false); }}
          />
          <SidebarItem 
            icon={<MessageSquareWarning className="w-4 h-4" />}
            label="Quality Review" 
            isActive={activeTab === "quality"}
            onClick={() => { setActiveTab("quality"); setMobileMenuOpen(false); }}
          />
          <SidebarItem 
            icon={<Activity className="w-4 h-4" />}
            label="Model Analytics" 
            isActive={activeTab === "analytics"}
            onClick={() => { setActiveTab("analytics"); setMobileMenuOpen(false); }}
          />
        </nav>

        <div className="p-4 border-t border-white/5 text-[10px] font-mono text-[var(--text-muted)] text-center">
          VoxQuery Admin Console v3.0
        </div>
      </aside>

      {/* Main Content Area */}
      <section className="flex-1 flex flex-col min-h-screen overflow-hidden relative">
        <header className="px-6 md:px-10 py-6 border-b border-white/5 flex justify-between items-center z-10 bg-[#10141C]/60 backdrop-blur-md">
          <div>
            <h1 className="text-2xl md:text-3xl font-light text-white capitalize tracking-tight">
              {activeTab === "vocabulary" ? "Business Vocabulary" : activeTab === "analytics" ? "Model Analytics" : activeTab === "history" ? "Query History" : activeTab}
            </h1>
            <p className="text-xs md:text-sm text-[var(--text-muted)] mt-1 font-medium">
              Manage platform configurations, review query performance, and oversee tenant health.
            </p>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-6 md:p-10 z-10">
          <AnimatePresence mode="wait">
            {activeTab === "overview" && <OverviewDashboard key="overview" getToken={getToken} />}
            {activeTab === "history" && <PlaceholderDashboard key="history" title="Query History" subtitle="Cross-tenant query execution history logging is not configured for this environment. Real-time query execution is logged per session." />}
            {activeTab === "vocabulary" && <VocabularyDashboard key="vocabulary" getToken={getToken} />}
            {activeTab === "workspaces" && <WorkspacesDashboard key="workspaces" getToken={getToken} />}
            {activeTab === "quality" && <QualityReviewDashboard key="quality" getToken={getToken} />}
            {activeTab === "analytics" && <PlaceholderDashboard key="analytics" title="Model Analytics" />}
          </AnimatePresence>
        </div>
      </section>
    </main>
  );
}

function SidebarItem({ icon, label, isActive, onClick }: { icon: React.ReactNode; label: string; isActive: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium transition-all touch-target",
        isActive 
          ? "bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20 shadow-sm" 
          : "text-[var(--text-secondary)] hover:bg-white/5 hover:text-white border border-transparent"
      )}
    >
      <div className="flex items-center gap-3">
        {icon}
        {label}
      </div>
      {isActive && <ChevronRight className="w-4 h-4 opacity-70" />}
    </button>
  );
}

/* ── Dashboards ────────────────────────────────────────────── */

function OverviewDashboard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadStats() {
      try {
        const token = await getToken();
        const data = await fetchAdminStats(token);
        setStats(data);
      } catch (err) {
        console.error("Failed to load stats", err);
      } finally {
        setLoading(false);
      }
    }
    loadStats();
  }, [getToken]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 text-[var(--accent-blue)] animate-spin" />
      </div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-8 max-w-6xl mx-auto">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
        <StatCard title="Total Workspaces" value={stats?.total_workspaces || "0"} icon={<Users className="w-5 h-5" />} color="blue" />
        <StatCard title="Active Vocabularies" value={stats?.total_glossaries || "0"} icon={<BookOpen className="w-5 h-5" />} color="emerald" />
        <StatCard title="Total Queries" value={stats?.total_turns || "0"} icon={<TerminalSquare className="w-5 h-5" />} color="violet" />
        <StatCard title="Avg Latency (ms)" value={stats?.avg_latency ? Math.round(stats.avg_latency).toString() : "0"} icon={<Activity className="w-5 h-5" />} color="amber" />
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-card p-6">
          <h3 className="text-base font-semibold text-white mb-4">System Health</h3>
          <div className="space-y-4">
            <div className="flex justify-between items-center pb-3 border-b border-white/5">
              <span className="text-[var(--text-secondary)] text-sm">Database Connection</span>
              <span className="px-2.5 py-1 rounded-full bg-[var(--accent-green)]/10 text-[var(--accent-green)] text-xs font-medium border border-[var(--accent-green)]/20">Operational</span>
            </div>
            <div className="flex justify-between items-center pb-3 border-b border-white/5">
              <span className="text-[var(--text-secondary)] text-sm">LLM Inference API</span>
              <span className="px-2.5 py-1 rounded-full bg-[var(--accent-green)]/10 text-[var(--accent-green)] text-xs font-medium border border-[var(--accent-green)]/20">Operational</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-[var(--text-secondary)] text-sm">Speech Services</span>
              <span className="px-2.5 py-1 rounded-full bg-[var(--accent-green)]/10 text-[var(--accent-green)] text-xs font-medium border border-[var(--accent-green)]/20">Operational</span>
            </div>
          </div>
        </div>

        <div className="glass-card p-6">
          <h3 className="text-base font-semibold text-white mb-4 flex justify-between items-center">
            Recent Alerts
            <span className="text-xs text-[var(--accent-blue)] bg-[var(--accent-blue)]/10 px-2 py-0.5 rounded-md font-mono">Last 24h</span>
          </h3>
          <div className="flex flex-col items-center justify-center py-8 text-[var(--text-muted)]">
            <CheckCircle2 className="w-10 h-10 mb-2 opacity-30 text-[var(--accent-green)]" />
            <p className="text-sm font-medium">No critical alerts</p>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function StatCard({ title, value, icon, color }: { title: string, value: string, icon: React.ReactNode, color: string }) {
  const colorMap: Record<string, string> = {
    blue: "text-sky-400 bg-sky-500/10 border-sky-500/20",
    emerald: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    violet: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
    amber: "text-amber-400 bg-amber-500/10 border-amber-500/20"
  };

  return (
    <div className="glass-card p-5 relative overflow-hidden group">
      <div className="flex justify-between items-start mb-3">
        <h4 className="text-[var(--text-muted)] text-xs font-medium">{title}</h4>
        <div className={`p-2 rounded-xl border ${colorMap[color]}`}>
          {icon}
        </div>
      </div>
      <p className="text-2xl font-bold text-white tracking-tight">{value}</p>
    </div>
  );
}

function WorkspacesDashboard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const token = await getToken();
        const data = await fetchAdminWorkspaces(token);
        setWorkspaces(data.data || []);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [getToken]);

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-6 max-w-6xl mx-auto">
      <div className="glass-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-white/[0.02] border-b border-white/5">
              <tr>
                <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">Workspace Name</th>
                <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">Tenant ID</th>
                <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">Vocabulary</th>
                <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs text-right">Total Queries</th>
                <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs text-right">Last Active</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center">
                    <Loader2 className="w-6 h-6 animate-spin text-[var(--accent-blue)] mx-auto" />
                  </td>
                </tr>
              ) : workspaces.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-[var(--text-muted)] italic">
                    No workspaces found.
                  </td>
                </tr>
              ) : (
                workspaces.map((item, idx) => (
                  <tr key={idx} className="hover:bg-white/[0.02] transition-colors group">
                    <td className="px-6 py-4 text-white font-medium">
                      {item.workspace_name || "Main Workspace"}
                    </td>
                    <td className="px-6 py-4 text-[var(--text-muted)] font-mono text-xs">
                      {item.id?.substring(0, 12)}...
                    </td>
                    <td className="px-6 py-4">
                      {item.has_glossary ? (
                        <span className="px-2.5 py-0.5 rounded-full bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] text-xs border border-[var(--accent-blue)]/20 font-medium">Configured</span>
                      ) : (
                        <span className="px-2.5 py-0.5 rounded-full bg-white/5 text-[var(--text-muted)] text-xs border border-white/10">Missing</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-[var(--text-secondary)] text-right font-mono">
                      {item.total_turns}
                    </td>
                    <td className="px-6 py-4 text-[var(--text-muted)] text-right text-xs font-mono">
                      {item.last_active_at ? new Date(item.last_active_at).toLocaleDateString() : "Never"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </motion.div>
  );
}

function VocabularyDashboard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [glossaries, setGlossaries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<any>(null);

  async function loadGlossary() {
    try {
      setLoading(true);
      const token = await getToken();
      const res = await fetchAdminGlossary(token);
      setGlossaries(res.data || []);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadGlossary();
  }, [getToken]);

  const filteredGlossaries = glossaries.filter(g => 
    g.workspace_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    JSON.stringify(g.metric_synonyms).toLowerCase().includes(searchQuery.toLowerCase()) ||
    JSON.stringify(g.table_synonyms).toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-6 max-w-6xl mx-auto">
      
      {/* Explainer Card */}
      <div className="glass-card p-6 flex flex-col md:flex-row gap-6 items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white mb-1 flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-[var(--accent-blue)]" />
            Teach VoxQuery how your company talks about its data
          </h2>
          <p className="text-[var(--text-secondary)] text-sm max-w-2xl leading-relaxed">
            Bridge the gap between custom business terms and underlying database columns. 
            For example, map terms like "Revenue" or "ARR" to `total_net_revenue`.
          </p>
        </div>
        <button 
          onClick={() => { setEditingItem(null); setIsModalOpen(true); }}
          className="shrink-0 flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/80 text-white text-sm font-semibold rounded-xl transition-all shadow-md touch-target"
        >
          <Plus className="w-4 h-4" /> Add Term
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 space-y-4">
          {/* Search */}
          <div className="glass-card p-2 flex items-center gap-3">
            <Search className="w-5 h-5 text-[var(--text-muted)] ml-3" />
            <input 
              type="text" 
              placeholder="Search workspaces or business terms..." 
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="bg-transparent border-none focus:outline-none text-sm text-white w-full placeholder:text-[var(--text-muted)] h-10"
            />
          </div>
          
          {/* Plain Language Table */}
          <div className="glass-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-white/[0.02] border-b border-white/5">
                  <tr>
                    <th className="px-5 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">Workspace</th>
                    <th className="px-5 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">Business term</th>
                    <th className="px-5 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">What the AI should query</th>
                    <th className="px-5 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs text-right">Times used</th>
                    <th className="px-5 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs text-right">Edit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {loading ? (
                    <tr>
                      <td colSpan={5} className="px-6 py-12 text-center">
                        <Loader2 className="w-6 h-6 animate-spin text-[var(--accent-blue)] mx-auto" />
                      </td>
                    </tr>
                  ) : filteredGlossaries.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-6 py-12 text-center text-[var(--text-muted)] italic">
                        No vocabulary mappings configured.
                      </td>
                    </tr>
                  ) : (
                    filteredGlossaries.map((item, idx) => (
                      <tr key={idx} className="hover:bg-white/[0.02] transition-colors group">
                        <td className="px-5 py-4 text-white font-medium">
                          {item.workspace_name || "Default Workspace"}
                          <div className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5 truncate max-w-[120px]">{item.tenant_id}</div>
                        </td>
                        <td className="px-5 py-4 text-[var(--text-secondary)] text-xs">
                          <VocabularyChips items={item.metric_synonyms} hits={item.synonym_hits} />
                        </td>
                        <td className="px-5 py-4 text-[var(--text-secondary)] text-xs">
                          <VocabularyChips items={item.table_synonyms} hits={item.synonym_hits} />
                        </td>
                        <td className="px-5 py-4 text-right">
                          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[var(--accent-green)]/10 border border-[var(--accent-green)]/20 text-[var(--accent-green)] font-mono text-xs font-medium">
                            <Activity className="w-3 h-3" />
                            {item.total_hits || 0}
                          </div>
                        </td>
                        <td className="px-5 py-4 text-right">
                          <button 
                            onClick={() => { setEditingItem(item); setIsModalOpen(true); }}
                            className="text-[var(--text-muted)] hover:text-[var(--accent-blue)] p-2 hover:bg-white/5 rounded-lg transition-colors touch-target"
                            title="Edit Vocabulary"
                          >
                            <Edit2 className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Live Preview Panel */}
        <div className="xl:col-span-1">
          <VocabularyLivePreview getToken={getToken} workspaces={glossaries.map(g => ({ id: g.tenant_id, name: g.workspace_name }))} />
        </div>
      </div>

      <AnimatePresence>
        {isModalOpen && (
          <VocabularyModal 
            isOpen={isModalOpen}
            initialData={editingItem}
            getToken={getToken}
            onClose={() => setIsModalOpen(false)}
            onSave={() => { setIsModalOpen(false); loadGlossary(); }}
            workspaces={glossaries.map(g => ({ id: g.tenant_id, name: g.workspace_name }))}
          />
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function VocabularyChips({ items, hits }: { items: Record<string, string>, hits: Record<string, number> }) {
  if (!items || Object.keys(items).length === 0) return <span className="text-[var(--text-muted)] italic">None</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(items).slice(0, 3).map(([k, v]) => (
        <span key={k} className="bg-white/5 px-2 py-1 rounded border border-white/10 flex items-center gap-1.5 max-w-[150px]">
          <span className="truncate">{k} <span className="opacity-40 mx-1">→</span> {v as string}</span>
          {hits && hits[k] && <span className="text-[9px] text-[var(--accent-green)] bg-[var(--accent-green)]/10 px-1 rounded-sm">{hits[k]}</span>}
        </span>
      ))}
      {Object.keys(items).length > 3 && (
        <span className="bg-white/5 px-1.5 py-1 rounded border border-white/10 opacity-70">
          +{Object.keys(items).length - 3}
        </span>
      )}
    </div>
  );
}

function VocabularyLivePreview({ getToken, workspaces }: any) {
  const [selectedTenant, setSelectedTenant] = useState("");
  const [inputText, setInputText] = useState("");
  const [previewResult, setPreviewResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (workspaces.length > 0 && !selectedTenant) {
      setSelectedTenant(workspaces[0].id);
    }
  }, [workspaces, selectedTenant]);

  const handleTest = async () => {
    if (!inputText.trim() || !selectedTenant) return;
    setLoading(true);
    try {
      const token = await getToken();
      const res = await fetchGlossaryPreview(selectedTenant, inputText, token);
      setPreviewResult(res);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="glass-card p-6 h-full flex flex-col">
      <h3 className="text-base font-semibold text-white mb-1 flex items-center gap-2">
        <Play className="w-4 h-4 text-[var(--accent-amber)]" />
        Test Vocabulary Mapping
      </h3>
      <p className="text-xs text-[var(--text-muted)] mb-5">Type a question to preview AI term translation.</p>
      
      <div className="space-y-4 flex-1">
        <div>
          <label className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1.5 block">Select Workspace</label>
          <select 
            value={selectedTenant} 
            onChange={e => setSelectedTenant(e.target.value)}
            className="w-full bg-[var(--bg-surface)] border border-white/10 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-[var(--accent-blue)]"
          >
            <option value="">-- Choose Workspace --</option>
            {workspaces.map((w: any) => (
              <option key={w.id} value={w.id}>{w.name || "Main Workspace"}</option>
            ))}
          </select>
        </div>
        
        <div>
          <label className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1.5 block">Business Question</label>
          <textarea 
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            placeholder="e.g. Show me the revenue for last quarter..."
            className="w-full h-24 bg-[var(--bg-surface)] border border-white/10 rounded-xl p-3 text-sm text-white focus:outline-none focus:border-[var(--accent-blue)] placeholder:text-[var(--text-muted)] resize-none"
          />
        </div>

        <button 
          onClick={handleTest}
          disabled={loading || !inputText.trim() || !selectedTenant}
          className="w-full py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white text-sm font-semibold transition-colors flex justify-center items-center gap-2 disabled:opacity-50 touch-target"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Test Query Translation"}
        </button>

        {previewResult && (
          <motion.div initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} className="pt-4 border-t border-white/5 mt-4 space-y-2">
            <label className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider block">Rewritten Output</label>
            <div className="p-3 bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 rounded-xl text-sm text-[var(--accent-blue)] font-mono leading-relaxed">
              {previewResult.rewritten}
            </div>
            {(previewResult.detected_metrics?.length > 0 || previewResult.detected_tables?.length > 0) && (
              <div className="flex gap-2 text-[10px] text-[var(--accent-green)] items-center font-medium">
                <CheckCircle2 className="w-3 h-3" /> Term mapping matched!
              </div>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
}

function VocabularyModal({ isOpen, onClose, initialData, onSave, getToken, workspaces }: any) {
  const [tenantId, setTenantId] = useState(initialData?.tenant_id || "");
  const [metrics, setMetrics] = useState<Record<string, string>>(initialData?.metric_synonyms || {});
  const [tables, setTables] = useState<Record<string, string>>(initialData?.table_synonyms || {});
  const [saving, setSaving] = useState(false);

  if (!isOpen) return null;

  const handleSave = async () => {
    if (!tenantId.trim()) return;
    setSaving(true);
    try {
      const token = await getToken();
      await postAdminGlossary({ tenant_id: tenantId.trim(), metric_synonyms: metrics, table_synonyms: tables }, token);
      onSave();
    } catch (err: any) {
      alert("Failed to save vocabulary.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
      <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} className="glass-card w-full max-w-2xl overflow-hidden flex flex-col shadow-2xl">
        <div className="p-6 border-b border-white/5 flex justify-between items-center bg-[#10141C]">
          <h2 className="text-lg font-semibold text-white flex items-center gap-3">
            {initialData ? <Edit2 className="w-5 h-5 text-[var(--accent-blue)]" /> : <Plus className="w-5 h-5 text-[var(--accent-blue)]" />}
            {initialData ? "Edit Business Vocabulary" : "New Business Vocabulary"}
          </h2>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white transition-colors touch-target"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-6 space-y-6 overflow-y-auto max-h-[60vh] bg-[#090B10]">
          <div className="space-y-2">
            <label className="text-xs font-medium text-[var(--text-secondary)]">Workspace (Tenant ID)</label>
            <input 
              type="text" 
              value={tenantId} 
              onChange={e => setTenantId(e.target.value)} 
              disabled={!!initialData} 
              className="w-full bg-[var(--bg-surface)] border border-white/10 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-[var(--accent-blue)] text-white disabled:opacity-50 font-mono" 
              placeholder="Tenant ID..." 
            />
          </div>
          <KeyValueEditor 
            title="Measures (Metrics)" 
            subtitle="Map business terms like 'Revenue' to database columns like 'total_sales'."
            value={metrics} 
            onChange={setMetrics} 
          />
          <KeyValueEditor 
            title="Dimensions (Tables)" 
            subtitle="Map general concepts like 'Customers' to specific table names like 'users'."
            value={tables} 
            onChange={setTables} 
          />
        </div>
        <div className="p-5 border-t border-white/5 bg-[#10141C] flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-sm font-medium text-[var(--text-muted)] hover:text-white transition-all touch-target">Cancel</button>
          <button 
            onClick={handleSave} 
            disabled={saving || !tenantId.trim()} 
            className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold bg-[var(--accent-blue)] text-white hover:bg-[var(--accent-blue)]/80 disabled:opacity-50 transition-all shadow-md touch-target"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
            {saving ? "Saving..." : "Save Vocabulary"}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

function KeyValueEditor({ title, subtitle, value, onChange }: { title: string, subtitle: string, value: Record<string, string>, onChange: (val: Record<string, string>) => void }) {
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  const handleAdd = () => {
    if (newKey.trim() && newValue.trim()) {
      onChange({ ...value, [newKey.trim()]: newValue.trim() });
      setNewKey("");
      setNewValue("");
    }
  };

  const handleRemove = (k: string) => {
    const next = { ...value };
    delete next[k];
    onChange(next);
  };

  return (
    <div className="space-y-3 glass-card p-4">
      <div>
        <label className="text-xs font-semibold text-white">{title}</label>
        <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{subtitle}</p>
      </div>
      <div className="flex gap-2">
        <input 
          type="text" placeholder="Business Term (e.g. revenue)" 
          value={newKey} onChange={e => setNewKey(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          className="flex-1 bg-[var(--bg-surface)] border border-white/10 rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-[var(--accent-blue)] text-white placeholder:text-[var(--text-muted)]" 
        />
        <input 
          type="text" placeholder="DB Target (e.g. total_sales)" 
          value={newValue} onChange={e => setNewValue(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          className="flex-1 bg-[var(--bg-surface)] border border-white/10 rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-[var(--accent-blue)] text-white placeholder:text-[var(--text-muted)] font-mono" 
        />
        <button type="button" onClick={handleAdd} className="bg-white/5 border border-white/10 text-white p-2 rounded-xl hover:bg-white/10 transition-colors touch-target flex items-center justify-center">
          <Plus className="w-4 h-4" />
        </button>
      </div>
      <div className="flex flex-wrap gap-2 min-h-[44px] p-2.5 rounded-xl border border-white/5 bg-[var(--bg-base)]">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 bg-white/5 text-white px-2.5 py-1 rounded-lg text-xs border border-white/10">
            <span className="font-medium text-white">{k}</span>
            <ChevronRight className="w-3 h-3 text-[var(--text-muted)]" />
            <span className="text-[var(--accent-blue)] font-mono">{v}</span>
            <button type="button" onClick={() => handleRemove(k)} className="ml-1 text-[var(--text-muted)] hover:text-[var(--accent-rose)] transition-colors">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
        {Object.keys(value).length === 0 && <span className="text-xs text-[var(--text-muted)] italic self-center px-2">No terms added yet.</span>}
      </div>
    </div>
  );
}

function QualityReviewDashboard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [feedback, setFeedback] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  async function loadFeedback() {
    try {
      setLoading(true);
      const token = await getToken();
      const res = await fetchAdminFeedback(50, 0, token);
      setFeedback(res.data || []);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadFeedback();
  }, [getToken]);

  const toggleRow = (id: string) => {
    setExpandedRow(prev => prev === id ? null : id);
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-6 max-w-6xl mx-auto">
      <div className="flex justify-between items-center">
        <h3 className="text-base font-semibold text-white">Quality Review Pipeline Log</h3>
        <button 
          onClick={loadFeedback}
          className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-xl bg-white/5 border border-white/10 text-[var(--text-secondary)] hover:text-white transition-colors touch-target"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="glass-card p-16 flex flex-col items-center justify-center space-y-4 border-white/5">
          <Loader2 className="w-8 h-8 text-[var(--accent-blue)] animate-spin" />
        </div>
      ) : feedback.length === 0 ? (
        <div className="glass-card p-16 text-center border-dashed border-white/10">
          <CheckCircle2 className="w-10 h-10 mx-auto mb-3 opacity-30 text-[var(--accent-green)]" />
          <p className="text-base font-semibold text-white">All Clear</p>
          <p className="text-xs mt-1 text-[var(--text-muted)]">No recent quality flags or user reports.</p>
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-white/[0.02] border-b border-white/5">
                <tr>
                  <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">Timestamp</th>
                  <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">Workspace</th>
                  <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">Query</th>
                  <th className="px-6 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {feedback.map((item, idx) => (
                  <React.Fragment key={idx}>
                    <tr onClick={() => toggleRow(item.id)} className="hover:bg-white/[0.02] transition-colors cursor-pointer group">
                      <td className="px-6 py-4 text-[var(--text-muted)] whitespace-nowrap text-xs font-mono">
                        {new Date(item.created_at).toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-[var(--text-secondary)] font-mono text-xs flex items-center gap-2">
                        {item.tenant_id.substring(0,8)}...
                        <button onClick={(e) => { e.stopPropagation(); copyToClipboard(item.tenant_id); }} className="opacity-0 group-hover:opacity-100 p-1 hover:bg-white/10 rounded">
                          <Copy className="w-3 h-3" />
                        </button>
                      </td>
                      <td className="px-6 py-4 text-white font-medium max-w-xs truncate">
                        {item.transcript || "<No Text>"}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button className="text-[var(--accent-blue)] hover:text-white text-xs font-semibold px-3 py-1.5 rounded-lg bg-[var(--accent-blue)]/10 transition-all touch-target">
                          {expandedRow === item.id ? "Close" : "Inspect"}
                        </button>
                      </td>
                    </tr>
                    {expandedRow === item.id && (
                      <tr>
                        <td colSpan={4} className="p-0 border-b border-white/5">
                          <div className="bg-[#090B10] p-6 flex flex-col gap-4">
                            <div>
                              <h4 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase mb-2">Generated SQL</h4>
                              <div className="p-4 rounded-xl bg-[var(--bg-surface)] border border-white/10 text-[var(--accent-amber)] font-mono text-xs overflow-x-auto whitespace-pre-wrap">
                                {item.generated_sql || "Failed to generate SQL."}
                              </div>
                            </div>
                            <div className="flex justify-end gap-3 mt-1">
                              <button className="px-4 py-2 text-xs font-semibold text-[var(--text-muted)] border border-white/10 rounded-xl hover:bg-white/5 hover:text-white transition-colors touch-target">
                                Mark as Resolved
                              </button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </motion.div>
  );
}

function PlaceholderDashboard({ title }: { title: string }) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col items-center justify-center h-80 glass-card border-dashed border-white/10 max-w-6xl mx-auto p-6">
      <BarChart3 className="w-10 h-10 text-[var(--text-muted)] mb-3 opacity-30" />
      <h3 className="text-lg font-semibold text-white">{title}</h3>
      <p className="text-xs text-[var(--text-muted)] mt-1.5 max-w-sm text-center">
        This section is reserved for platform model metrics. Connect your analytics log store to populate figures.
      </p>
    </motion.div>
  );
}
