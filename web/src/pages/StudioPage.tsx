import { useCallback, useEffect, useState, lazy, Suspense } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, type Artifact, type BrainstormPlan } from "@/lib/vigil";
const ArtifactCanvasTldraw = lazy(() =>
  import("@/components/ArtifactCanvasTldraw").then((m) => ({ default: m.ArtifactCanvasTldraw })),
);
import { useSearchParams } from "react-router-dom";
import { GatewayError } from "@/lib/ww";

const KINDS = ["proposal", "brief", "contract", "memo", "report"] as const;

export default function StudioPage() {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);

  // composer state
  const [brief, setBrief] = useState("");
  const [kind, setKind] = useState<string>("proposal");
  const [grounding, setGrounding] = useState("");

  // stage: think-first gate → draft
  const [plan, setPlan] = useState<BrainstormPlan | null>(null);
  const [planStub, setPlanStub] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // open artifact + refine
  const [active, setActive] = useState<Artifact | null>(null);
  const [refineText, setRefineText] = useState("");
  const [refining, setRefining] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { artifacts } = await vigil.studio.list();
      setArtifacts(artifacts);
      setAuthError(null);
    } catch (e) {
      if (e instanceof GatewayError && e.code === "NO_SESSION") setAuthError("Sign in to VIGIL to use the Studio.");
      else setAuthError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Open the artifact named in ?artifact= — e.g. the meeting wrap-up redirects
  // here straight onto the freshly-generated canvas.
  const [searchParams] = useSearchParams();
  useEffect(() => {
    const id = searchParams.get("artifact");
    if (id) vigil.studio.get(id).then(setActive).catch(() => {});
  }, [searchParams]);

  // Stage 1 — think first (the brainstorm gate). No artifact yet.
  const runBrainstorm = async () => {
    if (!brief.trim()) return;
    setThinking(true);
    setError(null);
    setPlan(null);
    try {
      const res = await vigil.studio.brainstorm(brief.trim(), kind, grounding.trim() || undefined);
      setPlan(res.plan);
      setPlanStub(res.stub);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setThinking(false);
    }
  };

  // Stage 2 — draft against an approved approach.
  const draftFrom = async (approachText: string) => {
    setDrafting(true);
    setError(null);
    try {
      const title = brief.trim().slice(0, 60) || "Untitled artifact";
      const art = await vigil.studio.create({
        title,
        kind,
        brief: brief.trim(),
        approach: approachText,
        grounding: grounding.trim() || undefined,
      });
      setActive(art);
      setPlan(null);
      setBrief("");
      setGrounding("");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDrafting(false);
    }
  };

  const open = async (id: string) => setActive(await vigil.studio.get(id));

  const remove = async (id: string) => {
    await vigil.studio.remove(id);
    if (active?.id === id) setActive(null);
    await refresh();
  };

  const refine = async () => {
    if (!active || !refineText.trim()) return;
    setRefining(true);
    try {
      const updated = await vigil.studio.refine(active.id, refineText.trim());
      setActive(updated);
      setRefineText("");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefining(false);
    }
  };

  const newBoard = async () => {
    try {
      const art = await vigil.studio.blankCanvas("New board");
      setActive(art);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const inputCls = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50";

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">Studio</h1>
          <p className="text-sm text-text-secondary">
            Draft, refine, and crystallize artifacts — or open an <em>infinite brainstorming board</em> and think with the agent.
          </p>
        </div>
        <Button onClick={() => void newBoard()}>+ New board</Button>
      </header>

      {authError && (
        <Card><CardContent className="py-4 text-sm" style={{ color: "#f59e0b" }}>{authError}</CardContent></Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        {/* ── Left: composer + brainstorm gate ── */}
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader><CardTitle>New artifact</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-2">
                {KINDS.map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setKind(k)}
                    className="rounded-full px-3 py-1 text-xs capitalize"
                    style={{
                      border: "1px solid currentColor",
                      opacity: kind === k ? 1 : 0.4,
                      background: kind === k ? "currentColor" : "transparent",
                      color: kind === k ? "var(--background, #000)" : "inherit",
                    }}
                  >
                    {k}
                  </button>
                ))}
              </div>
              <textarea
                className={inputCls}
                rows={4}
                placeholder="What do you want to create? e.g. 'A proposal to onboard Acme Corp onto our trading desk, 3-month pilot.'"
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
              />
              <details>
                <summary className="cursor-pointer text-xs text-text-secondary">Ground in source text (optional)</summary>
                <textarea
                  className={`${inputCls} mt-2`}
                  rows={3}
                  placeholder="Paste contract / invoice / notes the draft should cite…"
                  value={grounding}
                  onChange={(e) => setGrounding(e.target.value)}
                />
              </details>
              <Button onClick={() => void runBrainstorm()} disabled={thinking || !brief.trim()} className="w-full">
                {thinking ? "Thinking…" : "Think it through →"}
              </Button>
              {error && <p className="text-xs" style={{ color: "#ff3366" }}>{error}</p>}
            </CardContent>
          </Card>

          {plan && (
            <Card>
              <CardHeader>
                <CardTitle>Approaches {planStub && <span className="text-xs font-normal text-text-secondary">(stub — set an LLM key for live)</span>}</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {plan.understanding && <p className="text-sm">{plan.understanding}</p>}
                {plan.clarifying_questions?.length > 0 && (
                  <div className="text-xs text-text-secondary">
                    <p className="mb-1 font-semibold uppercase tracking-wide">Worth clarifying</p>
                    <ul className="list-disc pl-4">
                      {plan.clarifying_questions.map((q, i) => <li key={i}>{q}</li>)}
                    </ul>
                  </div>
                )}
                <div className="flex flex-col gap-3">
                  {plan.approaches?.map((a, i) => (
                    <div key={i} className="rounded-md border border-current/15 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold">{a.name}</span>
                        {a.recommended && <span className="rounded px-2 py-0.5 text-[10px] uppercase" style={{ background: "#059669", color: "#fff" }}>Recommended</span>}
                      </div>
                      <p className="mt-1 text-sm">{a.summary}</p>
                      {a.tradeoffs && <p className="mt-1 text-xs text-text-secondary">Trade-offs: {a.tradeoffs}</p>}
                      <Button
                        ghost
                        className="mt-2"
                        disabled={drafting}
                        onClick={() => void draftFrom(`${a.name}: ${a.summary}\n\nDesign: ${plan.recommended_design}`)}
                      >
                        {drafting ? "Drafting…" : "Approve & draft this →"}
                      </Button>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader><CardTitle>Your artifacts</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-2">
              {artifacts.length === 0 && <p className="text-sm text-text-secondary">No artifacts yet.</p>}
              {artifacts.map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-2 rounded-md border border-current/10 px-3 py-2">
                  <button type="button" className="min-w-0 flex-1 text-left" onClick={() => void open(a.id)}>
                    <span className="block truncate text-sm font-medium">{a.title}</span>
                    <span className="text-xs capitalize text-text-secondary">{a.kind} · {new Date(a.updated_at).toLocaleDateString()}{a.revisions > 0 ? ` · rev ${a.revisions}` : ""}</span>
                  </button>
                  <button type="button" className="text-xs text-text-secondary hover:text-foreground" onClick={() => void remove(a.id)}>Delete</button>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* ── Right: open artifact + refine ── */}
        <div>
          {active ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="truncate">{active.title}</span>
                  <button type="button" className="text-xs text-text-secondary hover:text-foreground" onClick={() => setActive(null)}>Close</button>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {active.canvas ? (
                  <Suspense fallback={<div className="p-6 text-center text-sm text-text-secondary">Loading canvas…</div>}>
                    <ArtifactCanvasTldraw artifact={active} />
                  </Suspense>
                ) : (
                  <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap rounded-md border border-current/10 bg-current/5 p-3 text-sm leading-relaxed">{active.content}</pre>
                )}
                <div className="flex flex-col gap-2">
                  <input
                    className={inputCls}
                    placeholder="Refine… e.g. 'make it shorter, add a 3-week timeline'"
                    value={refineText}
                    onChange={(e) => setRefineText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") void refine(); }}
                  />
                  <Button onClick={() => void refine()} disabled={refining || !refineText.trim()} className="w-full">
                    {refining ? "Refining…" : "Refine with the agent"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="flex min-h-[200px] items-center justify-center text-center text-sm text-text-secondary">
                Open an artifact, or write a brief and let the agent think it through first.
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
