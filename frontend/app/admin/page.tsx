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
  TerminalSquare
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
      <main className="min-h-screen bg-[var(--bg-base)] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-[var(--accent-blue)] animate-spin" />
      </main>
    );
  }

  if (!isSignedIn) {
    return (
      <main className="min-h-screen bg-[var(--bg-base)] flex flex-col items-center justify-center p-4">
        <section className="glass-card p-8 max-w-md w-full text-center space-y-6">
          <ShieldAlert className="w-12 h-12 text-[var(--accent-rose)] mx-auto" />
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Admin Access Required</h1>
          <p className="text-[var(--text-secondary)]">You must sign in as an administrator to view this page.</p>
        </section>
      </main>
    );
  }

  return <AdminDashboard getToken={getToken} />;
}

type TabType = "overview" | "vocabulary" | "workspaces" | "quality" | "analytics";

function AdminDashboard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [activeTab, setActiveTab] = useState<TabType>("overview");

  return (
    <main className="min-h-screen flex bg-[#050505]">
      {/* Sidebar */}
      <aside className="w-64 border-r border-white/5 bg-black/40 backdrop-blur-xl flex flex-col relative z-20">
        <div className="p-6">
          <h2 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-indigo-500 bg-clip-text text-transparent flex items-center gap-2">
            <Settings className="w-6 h-6 text-blue-500" />
            VoxAdmin
          </h2>
        </div>
        
        <nav className="flex-1 px-4 space-y-1.5 mt-2">
          <SidebarItem 
            icon={<LayoutDashboard className="w-4 h-4" />}
            label="Overview" 
            isActive={activeTab === "overview"}
            onClick={() => setActiveTab("overview")}
          />
          <SidebarItem 
            icon={<BookOpen className="w-4 h-4" />}
            label="Business Vocabulary" 
            isActive={activeTab === "vocabulary"}
            onClick={() => setActiveTab("vocabulary")}
          />
          <SidebarItem 
            icon={<Users className="w-4 h-4" />}
            label="Workspaces" 
            isActive={activeTab === "workspaces"}
            onClick={() => setActiveTab("workspaces")}
          />
          <SidebarItem 
            icon={<MessageSquareWarning className="w-4 h-4" />}
            label="Quality Review" 
            isActive={activeTab === "quality"}
            onClick={() => setActiveTab("quality")}
          />
          <SidebarItem 
            icon={<Activity className="w-4 h-4" />}
            label="Analytics" 
            isActive={activeTab === "analytics"}
            onClick={() => setActiveTab("analytics")}
          />
        </nav>

        <div className="p-4 border-t border-white/5 text-xs text-white/30 text-center">
          VoxQuery Admin Console v3.0
        </div>
      </aside>

      {/* Main Content Area */}
      <section className="flex-1 flex flex-col h-screen overflow-hidden relative">
        {/* Ambient Top Glow */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-4xl h-96 bg-blue-500/10 blur-[100px] pointer-events-none rounded-full" />
        
        <header className="px-10 py-8 border-b border-white/5 flex justify-between items-center z-10 bg-black/20 backdrop-blur-md">
          <div>
            <h1 className="text-3xl font-light text-white capitalize tracking-tight">
              {activeTab.replace("-", " ")}
            </h1>
            <p className="text-sm text-white/50 mt-2 font-medium">
              Manage platform configurations, review RAG performance, and oversee tenant health.
            </p>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-10 z-10">
          <AnimatePresence mode="wait">
            {activeTab === "overview" && <OverviewDashboard key="overview" getToken={getToken} />}
            {activeTab === "vocabulary" && <VocabularyDashboard key="vocabulary" getToken={getToken} />}
            {activeTab === "workspaces" && <WorkspacesDashboard key="workspaces" getToken={getToken} />}
            {activeTab === "quality" && <QualityReviewDashboard key="quality" getToken={getToken} />}
            {activeTab === "analytics" && <PlaceholderDashboard key="analytics" title="Platform Analytics" />}
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
        "w-full flex items-center justify-between px-3 py-3 rounded-xl text-sm font-medium transition-all group",
        isActive 
          ? "bg-blue-500/10 text-blue-400 border border-blue-500/20 shadow-[0_0_20px_rgba(59,130,246,0.15)]" 
          : "text-white/60 hover:bg-white/5 hover:text-white border border-transparent"
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
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-8 max-w-6xl mx-auto">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <StatCard title="Total Workspaces" value={stats?.total_workspaces || "0"} icon={<Users className="w-5 h-5" />} color="blue" />
        <StatCard title="Active Vocabularies" value={stats?.total_glossaries || "0"} icon={<BookOpen className="w-5 h-5" />} color="emerald" />
        <StatCard title="Total Queries" value={stats?.total_turns || "0"} icon={<TerminalSquare className="w-5 h-5" />} color="violet" />
        <StatCard title="Avg Latency (ms)" value={stats?.avg_latency ? Math.round(stats.avg_latency).toString() : "0"} icon={<Activity className="w-5 h-5" />} color="amber" />
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-card p-6 border-white/5">
          <h3 className="text-lg font-medium text-white mb-4">System Health</h3>
          <div className="space-y-4">
            <div className="flex justify-between items-center pb-4 border-b border-white/5">
              <span className="text-white/70 text-sm">Database Connection</span>
              <span className="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 text-xs font-medium border border-emerald-500/20">Operational</span>
            </div>
            <div className="flex justify-between items-center pb-4 border-b border-white/5">
              <span className="text-white/70 text-sm">LLM Inference API</span>
              <span className="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 text-xs font-medium border border-emerald-500/20">Operational</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-white/70 text-sm">Speech Services</span>
              <span className="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 text-xs font-medium border border-emerald-500/20">Operational</span>
            </div>
          </div>
        </div>

        <div className="glass-card p-6 border-white/5">
          <h3 className="text-lg font-medium text-white mb-4 flex justify-between items-center">
            Recent Alerts
            <span className="text-xs text-blue-400 bg-blue-400/10 px-2 py-1 rounded-md">Last 24h</span>
          </h3>
          <div className="flex flex-col items-center justify-center py-10 text-white/40">
            <CheckCircle2 className="w-12 h-12 mb-3 opacity-20" />
            <p>No critical alerts.</p>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function StatCard({ title, value, icon, color }: { title: string, value: string, icon: React.ReactNode, color: string }) {
  const colorMap: Record<string, string> = {
    blue: "text-blue-400 bg-blue-500/10 border-blue-500/20",
    emerald: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    violet: "text-violet-400 bg-violet-500/10 border-violet-500/20",
    amber: "text-amber-400 bg-amber-500/10 border-amber-500/20"
  };

  return (
    <div className="glass-card p-6 border-white/5 hover:border-white/10 transition-colors relative overflow-hidden group">
      <div className={`absolute -right-4 -top-4 w-24 h-24 rounded-full blur-2xl opacity-20 group-hover:opacity-40 transition-opacity bg-${color}-500`} />
      <div className="flex justify-between items-start mb-4">
        <h4 className="text-white/60 text-sm font-medium">{title}</h4>
        <div className={`p-2 rounded-lg border ${colorMap[color]}`}>
          {icon}
        </div>
      </div>
      <p className="text-3xl font-bold text-white tracking-tight">{value}</p>
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
      <div className="glass-card overflow-hidden border-white/5">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-white/[0.02] border-b border-white/5">
              <tr>
                <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Workspace Name</th>
                <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Tenant ID</th>
                <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Has Vocabulary</th>
                <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs text-right">Total Queries</th>
                <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs text-right">Last Active</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center">
                    <Loader2 className="w-6 h-6 animate-spin text-blue-500 mx-auto" />
                  </td>
                </tr>
              ) : workspaces.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-white/40 italic">
                    No workspaces found.
                  </td>
                </tr>
              ) : (
                workspaces.map((item, idx) => (
                  <tr key={idx} className="hover:bg-white/[0.02] transition-colors group">
                    <td className="px-6 py-4 text-white font-medium">
                      {item.workspace_name}
                    </td>
                    <td className="px-6 py-4 text-white/50 font-mono text-xs">
                      {item.id}
                    </td>
                    <td className="px-6 py-4">
                      {item.has_glossary ? (
                        <span className="px-2.5 py-1 rounded-full bg-blue-500/10 text-blue-400 text-xs border border-blue-500/20 font-medium">Configured</span>
                      ) : (
                        <span className="px-2.5 py-1 rounded-full bg-white/5 text-white/40 text-xs border border-white/10">Missing</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-white/70 text-right">
                      {item.total_turns}
                    </td>
                    <td className="px-6 py-4 text-white/50 text-right text-xs">
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
      <div className="glass-card p-6 border-blue-500/20 bg-gradient-to-r from-blue-900/20 to-transparent flex flex-col md:flex-row gap-6 items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white mb-2 flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-blue-400" />
            Business Vocabulary Mapping
          </h2>
          <p className="text-white/60 text-sm max-w-2xl leading-relaxed">
            Bridge the gap between technical database column names and the terminology your business users actually use. 
            When a user asks about "Revenue", the engine will automatically map it to the underlying `total_sales_amount` metric.
          </p>
        </div>
        <button 
          onClick={() => { setEditingItem(null); setIsModalOpen(true); }}
          className="shrink-0 flex items-center gap-2 px-6 py-3 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-xl transition-all shadow-[0_0_20px_rgba(59,130,246,0.3)] hover:shadow-[0_0_30px_rgba(59,130,246,0.5)] transform hover:-translate-y-0.5"
        >
          <Plus className="w-4 h-4" /> Add Vocabulary
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 space-y-4">
          {/* Search */}
          <div className="glass-card p-2 border-white/5 flex items-center gap-3">
            <Search className="w-5 h-5 text-white/30 ml-3" />
            <input 
              type="text" 
              placeholder="Search workspaces or terms..." 
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="bg-transparent border-none focus:outline-none text-sm text-white w-full placeholder:text-white/30 h-10"
            />
          </div>
          
          {/* List */}
          <div className="glass-card overflow-hidden border-white/5">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-white/[0.02] border-b border-white/5">
                  <tr>
                    <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Workspace</th>
                    <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Measures</th>
                    <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Dimensions</th>
                    <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs text-right">Hit Rate</th>
                    <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {loading ? (
                    <tr>
                      <td colSpan={5} className="px-6 py-12 text-center">
                        <Loader2 className="w-6 h-6 animate-spin text-blue-500 mx-auto" />
                      </td>
                    </tr>
                  ) : filteredGlossaries.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-6 py-12 text-center text-white/40 italic">
                        No vocabularies configured.
                      </td>
                    </tr>
                  ) : (
                    filteredGlossaries.map((item, idx) => (
                      <tr key={idx} className="hover:bg-white/[0.02] transition-colors group">
                        <td className="px-6 py-4 text-white font-medium">
                          {item.workspace_name}
                          <div className="text-[10px] text-white/30 font-mono mt-1 truncate max-w-[120px]">{item.tenant_id}</div>
                        </td>
                        <td className="px-6 py-4 text-white/60 text-xs">
                          <VocabularyChips items={item.metric_synonyms} hits={item.synonym_hits} />
                        </td>
                        <td className="px-6 py-4 text-white/60 text-xs">
                          <VocabularyChips items={item.table_synonyms} hits={item.synonym_hits} />
                        </td>
                        <td className="px-6 py-4 text-right">
                          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-mono text-xs">
                            <Activity className="w-3 h-3" />
                            {item.total_hits || 0}
                          </div>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <button 
                            onClick={() => { setEditingItem(item); setIsModalOpen(true); }}
                            className="text-white/50 hover:text-blue-400 p-2 hover:bg-blue-500/10 rounded-lg transition-colors"
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
            workspaces={glossaries.map(g => ({ id: g.tenant_id, name: g.workspace_name }))} // Note: Usually we'd fetch all workspaces here, but passing existing is fine for edit
          />
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function VocabularyChips({ items, hits }: { items: Record<string, string>, hits: Record<string, number> }) {
  if (!items || Object.keys(items).length === 0) return <span className="text-white/30 italic">None</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(items).slice(0, 3).map(([k, v]) => (
        <span key={k} className="bg-white/5 px-2 py-1 rounded border border-white/10 flex items-center gap-2 max-w-[150px]">
          <span className="truncate">{k} <span className="opacity-40 mx-1">→</span> {v as string}</span>
          {hits && hits[k] && <span className="text-[9px] text-emerald-400 bg-emerald-500/10 px-1 rounded-sm">{hits[k]}</span>}
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

  // Set default tenant if available
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
    <div className="glass-card p-6 border-white/5 h-full flex flex-col">
      <h3 className="text-lg font-medium text-white mb-1 flex items-center gap-2">
        <Play className="w-4 h-4 text-amber-400" />
        Test It: Live Preview
      </h3>
      <p className="text-sm text-white/50 mb-6">Type a query to see how the vocabulary rewrites terms.</p>
      
      <div className="space-y-4 flex-1">
        <div>
          <label className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-2 block">Select Workspace</label>
          <select 
            value={selectedTenant} 
            onChange={e => setSelectedTenant(e.target.value)}
            className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option value="">-- Choose Workspace --</option>
            {workspaces.map((w: any) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </select>
        </div>
        
        <div>
          <label className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-2 block">User Query</label>
          <textarea 
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            placeholder="e.g. Show me the revenue for last quarter..."
            className="w-full h-24 bg-black/40 border border-white/10 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-blue-500 placeholder:text-white/20 resize-none"
          />
        </div>

        <button 
          onClick={handleTest}
          disabled={loading || !inputText.trim() || !selectedTenant}
          className="w-full py-2.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white text-sm font-medium transition-colors flex justify-center items-center gap-2 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Run Translation"}
        </button>

        {previewResult && (
          <motion.div initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} className="pt-4 border-t border-white/5 mt-4 space-y-3">
            <label className="text-xs font-semibold text-white/40 uppercase tracking-wider block">Rewritten Output</label>
            <div className="p-3 bg-blue-500/5 border border-blue-500/20 rounded-lg text-sm text-blue-100 font-mono leading-relaxed">
              {previewResult.rewritten}
            </div>
            {(previewResult.detected_metrics?.length > 0 || previewResult.detected_tables?.length > 0) && (
              <div className="flex gap-2 text-[10px] text-emerald-400 items-center">
                <CheckCircle2 className="w-3 h-3" /> Successfully mapped terms!
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
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} className="glass-card w-full max-w-2xl overflow-hidden flex flex-col shadow-2xl border border-white/10">
        <div className="p-6 border-b border-white/5 flex justify-between items-center bg-black/40">
          <h2 className="text-xl font-medium text-white flex items-center gap-3">
            {initialData ? <Edit2 className="w-5 h-5 text-blue-400" /> : <Plus className="w-5 h-5 text-blue-400" />}
            {initialData ? "Edit Business Vocabulary" : "New Business Vocabulary"}
          </h2>
          <button onClick={onClose} className="text-white/40 hover:text-white transition-colors"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-8 space-y-8 overflow-y-auto max-h-[60vh] bg-[#050505]">
          <div className="space-y-2">
            <label className="text-sm font-medium text-white/70">Workspace (Tenant)</label>
            <input 
              type="text" 
              value={tenantId} 
              onChange={e => setTenantId(e.target.value)} 
              disabled={!!initialData} 
              className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500 text-white disabled:opacity-50 font-mono" 
              placeholder="Paste Tenant UUID..." 
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
        <div className="p-6 border-t border-white/5 bg-black/40 flex justify-end gap-3">
          <button onClick={onClose} className="px-5 py-2.5 rounded-lg text-sm font-medium text-white/60 hover:text-white hover:bg-white/5 transition-all">Cancel</button>
          <button 
            onClick={handleSave} 
            disabled={saving || !tenantId.trim()} 
            className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 transition-all shadow-[0_0_15px_rgba(37,99,235,0.4)]"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
            {saving ? "Saving..." : "Save Configuration"}
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
    <div className="space-y-4 glass-card p-5 border-white/5">
      <div>
        <label className="text-sm font-medium text-white">{title}</label>
        <p className="text-xs text-white/40 mt-1">{subtitle}</p>
      </div>
      <div className="flex gap-2">
        <input 
          type="text" placeholder="Business Term (e.g. revenue)" 
          value={newKey} onChange={e => setNewKey(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          className="flex-1 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-white placeholder:text-white/30" 
        />
        <input 
          type="text" placeholder="DB Target (e.g. total_sales)" 
          value={newValue} onChange={e => setNewValue(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          className="flex-1 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-white placeholder:text-white/30 font-mono" 
        />
        <button type="button" onClick={handleAdd} className="bg-white/5 border border-white/10 text-white p-2 rounded-lg hover:bg-white/10 transition-colors">
          <Plus className="w-5 h-5" />
        </button>
      </div>
      <div className="flex flex-wrap gap-2 min-h-[50px] p-3 rounded-lg border border-white/5 bg-black/20">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 bg-white/5 text-white px-3 py-1.5 rounded-md text-xs border border-white/10 shadow-sm">
            <span className="font-medium text-white/80">{k}</span>
            <ChevronRight className="w-3 h-3 text-white/30" />
            <span className="text-blue-300 font-mono">{v}</span>
            <button type="button" onClick={() => handleRemove(k)} className="ml-2 text-white/30 hover:text-rose-400 transition-colors">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
        {Object.keys(value).length === 0 && <span className="text-xs text-white/30 italic self-center px-2">No terms added yet.</span>}
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
        <h3 className="text-lg font-medium text-white">Low Quality Pipeline Executions</h3>
        <button 
          onClick={loadFeedback}
          className="flex items-center gap-2 px-3 py-2 text-xs rounded-lg bg-white/5 border border-white/10 text-white/70 hover:text-white transition-colors"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="glass-card p-16 flex flex-col items-center justify-center space-y-4 border-white/5">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
        </div>
      ) : feedback.length === 0 ? (
        <div className="glass-card p-16 text-center border-dashed border-white/10 bg-black/20">
          <CheckCircle2 className="w-12 h-12 mx-auto mb-4 opacity-20 text-emerald-500" />
          <p className="text-lg text-white">All Clear.</p>
          <p className="text-sm mt-1 text-white/50">No recent quality flags or user reports.</p>
        </div>
      ) : (
        <div className="glass-card overflow-hidden border-white/5">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-white/[0.02] border-b border-white/5">
                <tr>
                  <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Timestamp</th>
                  <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Tenant</th>
                  <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs">Query</th>
                  <th className="px-6 py-4 font-semibold text-white/50 uppercase tracking-wider text-xs text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {feedback.map((item, idx) => (
                  <React.Fragment key={idx}>
                    <tr onClick={() => toggleRow(item.id)} className="hover:bg-white/[0.02] transition-colors cursor-pointer group">
                      <td className="px-6 py-4 text-white/50 whitespace-nowrap text-xs">
                        {new Date(item.created_at).toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-white/70 font-mono text-xs flex items-center gap-2">
                        {item.tenant_id.substring(0,8)}...
                        <button onClick={(e) => { e.stopPropagation(); copyToClipboard(item.tenant_id); }} className="opacity-0 group-hover:opacity-100 p-1 hover:bg-white/10 rounded">
                          <Copy className="w-3 h-3" />
                        </button>
                      </td>
                      <td className="px-6 py-4 text-white font-medium max-w-xs truncate">
                        {item.transcript || "<No Text>"}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button className="text-blue-400 hover:text-blue-300 text-xs font-medium px-3 py-1.5 rounded bg-blue-500/10 opacity-0 group-hover:opacity-100 transition-all">
                          {expandedRow === item.id ? "Close" : "Inspect"}
                        </button>
                      </td>
                    </tr>
                    {expandedRow === item.id && (
                      <tr>
                        <td colSpan={4} className="p-0 border-b border-white/5">
                          <div className="bg-black/60 p-6 flex flex-col gap-4">
                            <div>
                              <h4 className="text-xs font-semibold text-white/40 uppercase mb-2">Generated SQL</h4>
                              <div className="p-4 rounded-lg bg-[#0a0a0a] border border-white/5 text-amber-200 font-mono text-xs overflow-x-auto whitespace-pre-wrap">
                                {item.generated_sql || "Failed to generate SQL."}
                              </div>
                            </div>
                            <div className="flex justify-end gap-3 mt-2">
                              <button className="px-4 py-2 text-xs font-medium text-white/50 border border-white/10 rounded-lg hover:bg-white/5 hover:text-white transition-colors">
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
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col items-center justify-center h-96 glass-card border-dashed border-white/10 bg-black/20 max-w-6xl mx-auto">
      <BarChart3 className="w-12 h-12 text-white mb-4 opacity-10" />
      <h3 className="text-xl text-white/70">{title}</h3>
      <p className="text-sm text-white/40 mt-2 max-w-sm text-center">
        This module is currently in development for Phase 4 of the production rollout.
      </p>
    </motion.div>
  );
}
