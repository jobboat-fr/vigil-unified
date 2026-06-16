# Old Meeting Room → vigil-unified — audit, diagnosis & port map

Audit of the original VIGIL meeting room (`VIGIL/frntendv2` + `VIGIL/backendv2/
src/modules/meeting-room`, ~12k lines) and the plan to bring it into vigil-unified.

## What the old meeting room is
A live, multi-human meeting surface where an AI council **sits in the seat**:
listens to the transcript, and a panel of specialist advisors (CFO/CTO/Legal/
Product) decides — in real time — whether to **raise its hand** and contribute,
grounded in evidence + long-term memory, with avatars/voice/emotion, then
summarizes the meeting into commitments and **learns** from feedback.

## Full element inventory (every old endpoint, grouped)
- **Council orchestration:** `/tasks` `/scenarios` `/architecture-board` `/orchestrate` `/orchestrate/stream`
- **Live intervention (the brain):** `/rooms/:id/intervention-check` `/intervention-grant` `/intervention-dismiss` `/transcript`
- **Adaptive learning:** `/rooms/:id/feedback` `/outcome` `/weights` `PATCH /weights/:name` `/learn`
- **Evidence chain:** `/:id/evidence` `/anchors` `/anchor` `/evidence/transcript`
- **Summary / memory:** `/:id/summarize` `/summary`, postMeetingPipeline, shortTermMemory
- **Scope / runtime / escalation:** `/:id/scope` `/preflight` `/runtime` `/escalation/check` `/escalations` `/listen-turn` `/escalations/dispatch`
- **Speech coordination (real-time turn-taking):** `/:id/speech` `/participants` `/participants/join` `/ai/join` `/speech/request|grant|release` `/ai-presence/prepare`
- **Workers:** `/:id/workers` `/workers/dispatch` `/external-workers`, hermesMeetingWorker
- **Emotion (Hume):** `/emotion/utterance` `/hume/utterance|emotions|token|session` `/emotion/timeline`, humeEmotionMapper
- **Voice (TTS/STT):** `/rooms/:id/tts` `/stt` `/:id/tts/advisor` `/voices`, speechManager, voicePipeline
- **Avatars (Tavus + Beyond Presence):** `/tavus/*` `/beyond/*` `/:id/avatar-session|avatar-speak`, avatarCatalog, avatarSessions
- **Exports:** `/rooms/:id/export/notion|linear|google`, externalBridge
- **Meetings/plans:** `/meetings/:id/start` `/plans` CRUD `/:id/algorithm` `/algorithm/recommend`
- **Bots:** `/recall/webhook` (Recall.ai meeting bot)
- **Guest:** guestOnboarding, MeetingGuest page
- **Frontend:** `MeetingRoom.jsx` (1650L), `Room.jsx`, `Council.jsx`, `Meetings.jsx`, room panels (`AvatarPanel`, `LiveKitPanel`, `HumeVoicePanel`, `GuestLiveKitPanel`)

## Diagnosis — what's already in vigil-unified vs missing
**Already ported:** council orchestration (5-stage `winny/council` — providers on HF, scoring, registry, collective + SSE), room lifecycle/members/transcript/convene (`rooms.py`), `MeetingRoomPage.tsx`, behavioral-overlay *stage* in the collective.
**Missing:** the live **intervention brain**, adaptive **learning**, evidence chain, summarizer→commitments, short-term memory write-through, scope/escalation, real-time speech turn-taking, emotion, voice, avatars, exports, the rich UI.

**Data model:** the brain tables ALREADY exist in Supabase — `pattern_weights` (adaptive), `ai_interventions` (log), `advisor_decisions` (+`feedback_score`), `commitments`, `room_utterances`, `room_messages`. No migration needed for Phase 1–2.

## Dependency reality (why this is phased, not one drop)
Large parts need external services that must be provisioned + keyed: **Hume** (emotion/voice), **LiveKit** (media), **Tavus / Beyond Presence** (avatars), **Recall.ai** (meeting bots), **Notion/Linear/Google** (exports), TTS/STT providers, **mem0/pgvector** (long-term RAG). The council *brain* needs none of these — only the HF LLM we already wired.

## Phased port plan
- **Phase 1 — The brain (portable now, highest value):** short-term memory, `intervention-check` (specialist fan-out → judge → "raise hand"), behavioral overlay + `pattern_weights`, intervention logging (`ai_interventions`/`advisor_decisions`), the frontend "live advisor" mode. ← **building now**
- **Phase 2 — Learning & memory:** `feedback`/`outcome`/`weights`/`learn` loop (adjust pattern_weights from outcomes), summarizer → `commitments`, evidence anchors.
- **Phase 3 — Real-time coordination:** speech turn-taking, participants, escalation, scope/preflight/runtime (WebSocket).
- **Phase 4 — Media (needs services):** Hume emotion, voice TTS/STT, LiveKit panels, Tavus/Beyond avatars, Recall.ai bots.
- **Phase 5 — Exports:** Notion/Linear/Google.
- **Frontend:** port `MeetingRoom.jsx` UI incrementally alongside each phase.
