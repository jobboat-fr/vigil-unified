-- Ops Team (P0) — the agentic-company surface.
-- Departments are autonomous-per-run, on-demand agent units; a department is
-- only "live" once its selftest passes its effectiveness contract. Per-user,
-- RLS-on, app conventions (mirrors 013_mail.sql).

CREATE TABLE IF NOT EXISTS public.departments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL,
    slug            text NOT NULL,                         -- support|finance|revenue|eng|cos
    name            text NOT NULL,
    head_lens       text,                                  -- council head / reviewer label
    hermes_profile  text,                                  -- OVH profile (null in P0 in-gateway depts)
    mandate         text NOT NULL DEFAULT '',
    kpis            jsonb NOT NULL DEFAULT '[]'::jsonb,
    status          text NOT NULL DEFAULT 'provisioning',  -- provisioning|live|failing
    paused          boolean NOT NULL DEFAULT false,        -- kill switch
    guardrails      jsonb NOT NULL DEFAULT '{}'::jsonb,    -- caps + tool allowlist
    health          jsonb NOT NULL DEFAULT '{}'::jsonb,    -- success_rate, avg_cost_usd, p50_ms, last_result
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT departments_user_slug_unique UNIQUE (user_id, slug)
);

-- Saved on-demand job templates (reserved for later phases; P0 jobs are code-defined).
CREATE TABLE IF NOT EXISTS public.ops_jobs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL,
    department_id uuid NOT NULL REFERENCES public.departments(id) ON DELETE CASCADE,
    name          text NOT NULL,
    prompt        text NOT NULL DEFAULT '',
    input_schema  jsonb NOT NULL DEFAULT '{}'::jsonb,
    acceptance    jsonb NOT NULL DEFAULT '{}'::jsonb,
    budget        jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_selftest   boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- One on-demand run of a job.
CREATE TABLE IF NOT EXISTS public.ops_tasks (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL,
    department_id      uuid NOT NULL REFERENCES public.departments(id) ON DELETE CASCADE,
    job                text NOT NULL,                      -- code-defined job name (P0)
    trigger            text NOT NULL DEFAULT 'manual',     -- manual|webhook|cos|selftest
    title              text,
    input              jsonb NOT NULL DEFAULT '{}'::jsonb,
    status             text NOT NULL DEFAULT 'queued',     -- queued|working|done|blocked|halted
    accepted           boolean,
    hermes_session_id  text,
    output_artifact_id uuid,
    council_run_id     text,
    cost_usd           numeric(10,4) NOT NULL DEFAULT 0,
    tokens             integer NOT NULL DEFAULT 0,
    wall_ms            integer NOT NULL DEFAULT 0,
    tool_calls         integer NOT NULL DEFAULT 0,
    error              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- The company activity feed.
CREATE TABLE IF NOT EXISTS public.ops_events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL,
    department_id uuid REFERENCES public.departments(id) ON DELETE CASCADE,
    task_id       uuid,
    kind          text NOT NULL DEFAULT 'run',            -- run|selftest|guardrail|pause
    summary       text NOT NULL DEFAULT '',
    ts            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS departments_user_idx ON public.departments (user_id);
CREATE INDEX IF NOT EXISTS ops_tasks_user_dept_idx ON public.ops_tasks (user_id, department_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ops_events_user_ts_idx ON public.ops_events (user_id, ts DESC);

ALTER TABLE public.departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ops_jobs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ops_tasks    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ops_events   ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own departments" ON public.departments
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access departments" ON public.departments
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users manage own ops_jobs" ON public.ops_jobs
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access ops_jobs" ON public.ops_jobs
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users manage own ops_tasks" ON public.ops_tasks
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access ops_tasks" ON public.ops_tasks
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users manage own ops_events" ON public.ops_events
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access ops_events" ON public.ops_events
    FOR ALL USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION public.ops_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS departments_updated_at ON public.departments;
CREATE TRIGGER departments_updated_at BEFORE UPDATE ON public.departments
    FOR EACH ROW EXECUTE FUNCTION public.ops_touch_updated_at();

DROP TRIGGER IF EXISTS ops_tasks_updated_at ON public.ops_tasks;
CREATE TRIGGER ops_tasks_updated_at BEFORE UPDATE ON public.ops_tasks
    FOR EACH ROW EXECUTE FUNCTION public.ops_touch_updated_at();
