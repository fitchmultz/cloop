# CLOOP Life: Natural-Language Product Spec

## Instruction to the Builder

You are building the next evolution of CLOOP.

Work from this spec autonomously. Do not ask clarifying questions unless a decision materially changes the long-term product direction or would cause expensive rework if guessed incorrectly.

Do not overengineer. Build the simplest version that works now and can still support the medium-term vision. Avoid clever architecture for its own sake. However, do not make foundational decisions that will obviously become bottlenecks later.

The goal is not to build a generic AI assistant, a task manager, a journal, a reminder app, or a productivity dashboard. The goal is to build a product that helps users stop mentally carrying unresolved loops.

Use the existing CLOOP project as the foundation if useful, but do not preserve existing product language or UX if it conflicts with this spec.

Do not expose implementation complexity to the user. The user should not need to understand agents, memory layers, embeddings, retrieval, workflows, orchestration, dashboards, or internal system state.

The product should feel simple, personal, useful, and low-friction.

---

# 1. BLUF

Build a personal cognitive defragmenter for unresolved intent.

The user should be able to dump scattered thoughts, obligations, ideas, reminders, worries, and half-formed plans into one place. The app should organize them into clear loops, preserve useful context, resurface what matters, help the user decide what still deserves attention, prepare obvious next actions, and help close or release loops.

Consumer-facing concept:

> For the stuff you keep meaning to do.

Internal concept:

> A cognitive defragmenter for unresolved intent.

Core promise:

> Put it here so you can stop carrying it in your head.

---

# 2. Why This Exists

People do not merely forget things.

They also:

- avoid things
- defer things
- overestimate effort
- underestimate momentum
- lose context
- let ideas decay
- carry stale guilt
- become overwhelmed by open loops
- repeat mental reminders throughout the day
- reschedule reminders until the thing no longer matters
- fail to act because the next step feels ambiguous
- fail to act because they need someone to push them
- fail to act because everything feels equally important

Current tools do not solve this well.

Reminder apps remember items but do not reduce ambiguity.

To-do apps store obligations but often create more management burden.

Chatbots can discuss context but conversations sprawl, threads become messy, and memory is unreliable or too flat.

Journals preserve thoughts but do not actively help close loops.

The real burden is that the user’s brain becomes the persistence layer for unresolved cognitive state.

This app exists to take that burden off the user.

---

# 3. Core Product Thesis

Human loops become scattered across the mind like fragmented files on a disk.

A user may have pieces of the same loop spread across:

- memory
- screenshots
- emails
- calendar events
- reminders
- text messages
- browser tabs
- voice notes
- photos
- guilt
- anxiety
- half-formed ideas
- vague obligations

The app should act like a mental defragmenter.

It should collect scattered fragments, connect related context, reduce ambiguity, and make loops easier to retrieve, act on, archive, or release.

The product is successful when the user feels:

> I put it there, and now I do not have to keep mentally rehearsing it.

---

# 4. What the Product Is

The product is a conversational loop-closing system.

It helps the user:

- capture messy thoughts naturally
- turn thoughts into loops
- link loops to related context
- preserve useful memory
- detect stale or decaying loops
- resurface what matters
- prepare next actions
- reduce perceived effort
- challenge avoidance
- support cleanup
- close, archive, abandon, or delete loops

It is not simply about remembering.

It is about helping users follow through on things their past self thought mattered, and helping them decide when those things no longer deserve to be carried.

---

# 5. What the Product Is Not

Do not build:

- a generic AI assistant
- a chatbot with reminders
- a traditional to-do app
- a calendar clone
- a reminder app clone
- a journal app
- a therapy bot
- a fake friend
- an engineering dashboard
- a productivity operating system
- a project-management platform
- a workspace-oriented professional tool
- a command center
- an operations dashboard
- a complicated agent management console

Avoid product language like:

- workspace
- command center
- operations
- project dashboard
- orchestration
- agentic workflow platform
- productivity suite
- accountability partner

The product may have assistant-like behavior, but it should not be positioned as “an assistant.”

The product may have journal-like capture, but it should not be positioned as “a journal.”

The product may have reminders, but it should not be positioned as “a reminder app.”

The product may have accountability, but it should not be positioned as “an accountability partner.”

---

# 6. Intended User

Primary user:

A normal person with a lot of unresolved life loops.

Examples:

- a parent managing school, errands, work, appointments, house tasks, family logistics
- an adult managing job applications, personal obligations, projects, medication, errands, ideas
- a spouse carrying invisible household mental load
- a caregiver juggling someone else’s appointments, paperwork, medication, and follow-ups
- a person who often thinks of 20 things at night and does not want to manually create 20 reminders
- a person who reschedules reminders until they become meaningless
- a person who wants direct help deciding what actually matters

This is not aimed first at professional teams, executives, engineers, or enterprise workflows.

Professional use may emerge later, but the initial product should serve personal life.

The product should be usable by nontechnical people.

The interface should feel closer to texting, voice-dumping, or glancing at a simple list than managing software.

---

# 7. Core Human Value

The user gets:

- relief from mentally carrying things
- less context switching
- fewer repeated mental reminders
- lower effort to resume an old thought
- clearer next actions
- help deciding what no longer matters
- fewer stale obligations
- better momentum
- reduced overwhelm
- a trustworthy place to dump cognitive clutter
- a record of what they handled over time

The key emotional outcome:

> My life feels more manageable.

---

# 8. Core Business Value

This product can become habit-forming because unresolved intent is universal.

Everyone has things they keep meaning to do.

The product has a broad consumer surface because it is not limited to productivity nerds, software developers, or office workers.

It is differentiated because it manages intent state, not just information.

It can later expand into:

- families
- households
- caregivers
- personal admin
- workspaces
- professional follow-through
- document handling
- agentic execution

But the wedge should stay focused:

> Help people stop carrying unresolved loops in their head.

---

# 9. Core UX Principle

Capture must be frictionless.

The user should be able to dump messy input without choosing:

- project
- thread
- folder
- tag
- category
- priority
- deadline
- reminder time
- next action

The system should infer what it can.

If clarification is useful, ask lightly and optionally.

Do not turn capture into a form.

Do not make the user manage the system.

---

# 10. Primary Interaction Pattern

The user interacts primarily through a conversational feed.

The feed should allow:

- typing
- voice input
- pasted text
- screenshots
- photos
- links
- emails later
- other external inputs later

The user can dump scattered thoughts naturally:

> Need to update my DOE CR, cancel or update the PR, send availability to the recruiter, pick up medicine, apply to those other jobs, read the Bible, and look into getting a new shaft for my 9-iron.

The system should parse this into separate loops and organize them.

The user should not need separate threads for every topic.

The system should handle topic jumps.

The user should be able to move from job applications to medicine to a product idea to a family event in the same feed without breaking context management.

---

# 11. The Feed Is Not the Source of Truth

Do not treat chat history as the primary memory model.

Messages are evidence, context, and state transitions.

They are not the canonical source of truth.

Example:

> Yeah, I agree.

This message has no standalone meaning. It must be interpreted relative to the relevant concept, loop, prior statement, or clarification.

Do not blindly attach every message to the immediately previous message.

The user may jump topics frequently.

The system must infer whether a message is:

- a new loop
- an update to an existing loop
- a response to a clarification
- a completion signal
- a deferral signal
- a preference signal
- a tone signal
- a correction
- a related tangent
- an abandoned tangent
- a general reflection
- non-actionable commentary

Users hate repeating themselves. The product must preserve useful context and avoid making the user restate things.

---

# 12. Core Object: Loop

A loop is unresolved intent.

A loop is not necessarily a task.

A loop may be:

- an obligation
- a reminder
- an idea
- a worry
- a decision
- a follow-up
- a research topic
- a deferred action
- a recurring pattern
- an event-prep item
- a stale guilt item
- a waiting item
- a partially formed intention

Every loop should eventually move toward resolution.

Resolution can mean:

- completed
- delegated
- archived
- intentionally abandoned
- deleted
- transformed into a different loop
- merged into another loop
- scheduled
- marked waiting

No loop should rot indefinitely without the system noticing.

---

# 13. Loop Fields and Attributes

Each loop should preserve enough information to support long-term usefulness without requiring the user to over-specify it.

Important attributes:

- title
- plain-language summary
- original evidence/source
- created timestamp
- updated timestamp
- last touched by user timestamp
- last touched by agent/system timestamp
- last resurfaced timestamp
- last deferred timestamp
- completed/archived/deleted/abandoned timestamp when applicable
- current state
- urgency
- effort estimate
- confidence
- emotional weight estimate
- deadline if known
- related people
- related locations
- related events
- related loops
- blockers
- dependencies
- prepared next action
- suggested next step
- decay/staleness status
- user preference signals
- history of decisions or state changes

Timestamps are mandatory for meaningful reasoning.

Without timestamps, the system cannot reason about:

- decay
- avoidance
- urgency
- relevance
- repeated deferral
- stale priority
- pattern changes
- what is top-of-mind versus archived

---

# 14. Loop Lifecycle States

Support a simple lifecycle first, but design it so additional nuance can be added later.

Core states:

- captured
- active
- needs clarification
- prepared
- scheduled
- waiting
- blocked
- stale
- completed
- archived
- intentionally abandoned
- deleted

Do not overcomplicate the first implementation.

But do not collapse everything into only “open” and “done,” because that will become a limitation.

At minimum, the system must distinguish:

- active
- waiting/blocked
- stale
- completed
- archived/abandoned/deleted

The difference between archived, abandoned, and deleted matters:

- Archived means preserved but not active.
- Intentionally abandoned means the user chose to stop caring.
- Deleted means remove from useful history unless required for audit/undo.

---

# 15. Memory Must Be Layered

Do not implement memory as a single flat store.

Conceptually, memory should have separation of concerns.

The first implementation can be simple, but it must preserve the ability to separate memory types over time.

Important memory categories:

## Active Memory

Current unresolved loops and recently relevant context.

This is the user’s “mental RAM.”

It should be fast to retrieve and frequently considered.

## Warm Memory

Recent or related context that is not urgent but may support active loops.

Examples:

- recent job-search discussion
- known pharmacy location
- related project notes
- recent family event planning
- job application history
- current personal priorities

## Cold Memory

Completed, archived, abandoned, or historical context.

This should be retrievable but not constantly resurfaced.

Used for:

- audit trail
- historical lookup
- “what did I accomplish?”
- pattern analysis
- strong relevance checks

## Preference Memory

How the user wants help.

Examples:

- direct versus gentle tone
- blunt versus collaborative style
- preferred reminder style
- preferred autonomy level
- preferred pharmacy
- preferred stores
- whether cleanup should be aggressive
- whether the user likes quick wins first
- whether the user wants instructions or discussion for certain loop types

## Pattern Memory

Observed behavior patterns.

Examples:

- user defers errands until they become urgent
- user applies to jobs in bursts once momentum starts
- user overestimates job-application effort
- user ignores vague research tasks
- user needs stronger nudges on stale loops
- user likes direct accountability for errands
- user prefers collaborative exploration for creative ideas

## People and Context Memory

Known people, organizations, locations, and relationships.

Examples:

- spouse
- recruiter
- coworker
- DOE
- pharmacy
- golf shop
- church
- family members

## Event Memory

Events that collect loops.

Examples:

- job search
- DOE CR meeting
- medication refill
- golf equipment
- Bible reading habit
- camping trip
- wedding
- family appointment

---

# 16. Memory Must Decay, Compress, and Move

The system should not hold everything equally forever.

AI systems that hold onto everything forever become noisy and unhelpful.

The app must support:

- promotion to active memory
- demotion to warm memory
- archival into cold memory
- compression of repeated context
- merging duplicates
- preserving provenance
- confidence decay
- stale-loop detection
- pruning or deletion of noise
- user correction

The goal is not to remember everything.

The goal is to maintain useful continuity.

That distinction is critical.

---

# 17. Background Cleanup and Memory Gardening

The app should not rely only on user interactions to stay organized.

Conceptually, there should be background review behavior.

This can start simple.

It does not need to be an overbuilt multi-agent system.

But the product should support the idea that some cleanup happens outside the active conversation.

Background review should detect:

- stale loops
- duplicate loops
- loops that should be merged
- loops that should be archived
- loops with no next action
- loops with repeated deferrals
- loops that appear completed
- loops marked high priority but ignored
- active memory bloat
- preference or pattern changes
- context that should move between active, warm, and cold memory

The user-facing result should be simple:

> I cleaned up the obvious stuff. Three items need your call.

or:

> We have some cleanup. I suggest archiving these stale ideas and keeping these active.

Do not expose internal background-agent architecture to the user.

---

# 18. Specialized Internal Roles, But Do Not Overbuild Them

Conceptually, the system may have specialized responsibilities:

- capture
- loop extraction
- context linking
- resurfacing
- cleanup
- memory gardening
- preparation
- tone adaptation
- autonomy policy

The first implementation does not need separate sophisticated agents for each role.

However, the system should not become one giant undifferentiated blob where every feature is tangled together.

Preserve conceptual boundaries so the product can grow.

The user should never see these roles.

The user should experience one coherent product.

---

# 19. Intelligent Resurfacing

Resurfacing is central.

Do not build dumb reminders.

Time matters, but it is not the only factor.

Resurfacing should consider:

- deadline
- effort estimate
- emotional weight
- user’s current load
- age of loop
- number of deferrals
- last touched time
- whether the loop blocks something else
- whether the user tends to avoid this type of loop
- whether the app can prepare something useful first
- whether the loop is stale and needs cleanup
- whether the user asked to be pushed harder or softer
- whether the loop is important but not urgent
- whether it is urgent but low effort

Good resurfacing:

> Only one thing needs action before noon: update the DOE CR. Everything else can wait.

Bad resurfacing:

> Reminder: DOE CR.
> Reminder: medicine.
> Reminder: jobs.
> Reminder: Bible.
> Reminder: golf shaft.

The product should optimize for trust per nudge, not number of notifications.

---

# 20. Notification Philosophy

The app must not become notification spam.

Prefer:

- fewer nudges
- stronger relevance
- batched summaries
- user-triggered review
- digest-style updates
- cleanup sessions
- “what matters today?” answers
- context-rich nudges with clear rationale

Avoid:

- one notification per loop
- repeated nags
- generic reminder text
- resurfacing vague loops without next action
- asking for action when the app could have prepared more first

The user should feel:

> This only interrupts me when it matters.

---

# 21. Effort, Momentum, and Avoidance

The app should explicitly reduce perceived effort.

Humans often overestimate how hard something will be.

The app should identify:

- quick wins
- oversized loops
- vague loops
- blocked loops
- emotionally resisted loops
- loops that need splitting
- loops that are actually small but feel large

Examples:

> You have 12 open loops, but 4 are probably under 3 minutes. Clear those first?

> You’re treating this job application like a 2-hour project. The actual next step is only sending availability. That is a 3-minute loop.

> This has been sitting for three weeks. Either turn it into a 10-minute research brief or stop carrying it.

The app should help create momentum.

It should not merely preserve obligations.

---

# 22. Cleanup Is a First-Class Workflow

Cleanup is central to the product.

Most systems let tasks rot forever.

This app should not.

The app should detect unhealthy active-loop state.

Signals:

- too many active loops
- many stale loops
- many overdue loops
- repeated deferrals
- vague loops with no next action
- duplicate loops
- high-priority loops ignored for weeks
- loops not touched since capture
- loops that appear no longer relevant
- loops that are blocking other loops
- loops that are emotionally heavy but unclear

Bad cleanup:

> You have 50 unresolved tasks.

Better cleanup:

> We have some cleanup. I suggest closing 6, archiving 5, keeping 4, and reviewing 3. Want to go two at a time?

The app should be able to say:

> These look stale. My recommendation is to archive them unless you still care enough to spend time on them this week.

Cleanup should allow:

- complete
- archive
- delete
- reschedule
- delegate
- mark waiting
- mark still active
- mark no longer matters
- split
- merge
- ask for next action
- update priority
- update emotional importance

The user should be able to run cleanup conversationally:

> Quiz me on what’s open.

> Give me two at a time.

> Be aggressive.

> Only show me things that need a decision.

> Clean up anything obvious.

---

# 23. Prepared Actions

The app should reduce action friction before asking the user to act.

Prepared actions may include:

- drafted email
- drafted text
- call script
- checklist
- product shortlist
- application checklist
- errand plan
- route suggestion
- appointment prep
- summary of related context
- decision recommendation
- split into smaller steps
- “first 10 minutes” plan

Bad assistant behavior:

> If you want, I can draft that.

Better behavior:

> I drafted it. Review before send.

or:

> I found the apply link, summarized the role, and pulled the next step forward.

or:

> I cleaned up the obvious loops. Three need your decision.

The app should infer when the user wants suggestion, preparation, or action.

When the user says “send this,” do not draft and then ask if drafting was desired.

When the user says “help me decide,” do not act without a decision.

---

# 24. Autonomy and Delegated Authority

Do not force the user to micromanage the system.

The product should support delegated authority.

Autonomy should be configurable conversationally, not primarily through a complex settings UI.

Users should be able to say:

- never send emails without asking me
- never make purchases without approval
- never touch work emails without confirmation
- you can archive stale ideas without asking
- you can merge obvious duplicates
- you can clean up low-risk clutter aggressively
- always ask before messaging recruiters
- be conservative with job-related loops
- be aggressive with personal errands
- you can prepare carts but not buy
- you can mark loops complete when evidence is obvious, but show me afterward

The system should remember these as preferences.

The product needs guardrails, but too many guardrails create friction.

The rule:

> The agent acts within delegated authority. Meaningful actions are reversible or reviewable. Consequential actions require explicit approval unless the user has clearly delegated that exact class of action and the risk is acceptable.

---

# 25. Action Risk Levels

Use this conceptual policy.

Do not necessarily expose this taxonomy to the user.

## Level 0: Safe Internal Actions

Can usually happen automatically:

- organize loops
- infer groupings
- merge obvious duplicates
- prepare summaries
- estimate effort
- suggest priority
- draft next actions
- move stale items into review
- link related context
- update active/warm/cold memory placement

## Level 1: Reversible Internal Actions

Can happen if generally delegated, with undo/review:

- archive stale loops
- reschedule low-risk loops
- clean visible active list
- mark probably done when evidence is strong
- group related loops
- demote from active to warm memory
- compress memory

## Level 2: External Low-Risk Actions

Usually confirm unless delegated for that context:

- send casual text
- send non-sensitive email
- add calendar event
- create reminder
- share checklist
- save product to cart/list
- prepare but not submit

## Level 3: Consequential Actions

Require explicit approval:

- purchases
- job applications
- medical forms
- insurance/government/legal/financial submissions
- employer/recruiter/customer messages unless specifically delegated
- deleting important records
- irreversible actions
- reputationally sensitive communication

The system should err conservative for Level 3.

But it should not ask permission for every obvious internal action.

---

# 26. Undo, Review, and Trust

The product needs a clear way to review what the system did.

If the system archives something automatically, the user should be able to see that and restore it.

Examples:

> I archived 4 stale ideas. Say “show archived” if you want them back.

> I merged these two loops because they looked identical. Undo?

> I marked this probably done based on your message. Correct me if wrong.

Undo/review prevents micromanagement.

The system should be allowed to act within safe boundaries, but the user must be able to recover from mistakes.

Trust comes from:

- provenance
- reversibility
- clear rationale
- not doing consequential things silently
- not asking permission for obvious internal cleanup
- remembering user corrections

---

# 27. Tone and Personality

Tone must not be generic AI slop.

Avoid:

- “Great question!”
- “If you want, I can…”
- “It sounds like you’re feeling…”
- “Here are some steps you might consider…”
- fake therapy language
- sterile productivity language
- excessive hedging
- excessive cheerleading
- robotic formality

The tone should feel like a competent, familiar helper.

Some users want gentle support.

Some users want direct accountability.

Some users want blunt momentum.

Some users want collaborative reasoning.

Some users want to be told what to do.

Some users want to talk it out.

The system should learn tone over time.

Initial dogfood tone should be direct, practical, and momentum-oriented.

Example:

> This has been sitting for two weeks. Either act on it or stop carrying it. My recommendation: archive it unless you still care enough to spend 10 minutes on it today.

But tone should be adaptable.

The system should not become insulting, manipulative, or pseudo-therapeutic.

It may be direct.

It should not shame the user.

It should create momentum and relief.

---

# 28. Clarification Behavior

Clarification should be optional, lightweight, and contextual.

Do not make clarification a blocking wizard.

Example:

User:

> Need to pick up medicine.

System:

> Captured. Assuming CostMedica unless different.

If the user corrects it, update memory.

Example:

User:

> Need to get back to Ryan about this weekend.

System:

> Captured. Is this related to the camping plan with Ryan, or separate?

Clarification should happen when it materially improves:

- urgency
- effort estimate
- related context
- location
- deadline
- next action
- autonomy policy
- risk classification

Do not ask clarifying questions merely because the system could.

Ask only when useful.

---

# 29. Context Linking and Duplicate Handling

The app should link related loops and prevent duplicates.

If the user repeatedly mentions the same thing, the system should update the existing loop rather than create many duplicates.

Example:

- “Need medicine”
- “Pick up prescription”
- “Medicine got refilled yesterday”
- “Need to go to CostMedica”

These should likely become one loop with enriched context, not four separate tasks.

But do not over-merge distinct loops.

The system should distinguish:

- same loop
- related loop
- sub-loop
- supporting context
- separate loop under same event

When uncertain, present a lightweight prompt:

> This looks related to your medication pickup loop. I’ll attach it there unless it’s separate.

---

# 30. Views and Interface

The interface should be simple.

Primary surfaces:

## Capture Feed

The main interaction.

The user dumps thoughts and receives concise, useful responses.

## Open Loops View

A plain-language view of what is unresolved.

Not an engineering dashboard.

Possible groupings:

- Needs attention today
- Quick wins
- Waiting on someone
- Prepared for review
- Stale and needs a decision
- Upcoming
- Ideas, not tasks

## Cleanup View or Mode

A guided conversational cleanup process.

The user can say:

> Clean this up.

> Quiz me on what’s open.

> Go two at a time.

## History / Archive

A way to see what was completed, archived, abandoned, or deleted.

This matters because it feels good to look back and see what was handled.

It also supports auditability and trust.

Do not overbuild a complex UI.

The user should mostly interact conversationally.

The views should support clarity, not management overhead.

---

# 31. Example Workflows

## Workflow 1: Night Brain Dump

User:

> I need to send availability to that recruiter, pick up medicine, research that supplement, update my DOE CR, and look into the golf shaft.

System:

> Captured. I split that into 5 loops.
>
> What matters first:
> 1. DOE CR: likely urgent today.
> 2. Recruiter availability: quick win.
> 3. Medicine: refilled yesterday, pickup window started.
>
> Supplement research and golf shaft are low-pressure. I’ll keep them warm unless you want to act now.

## Workflow 2: What Am I Missing?

User:

> What am I missing?

System:

> Three things actually matter right now:
>
> 1. DOE CR needs action before the meeting.
> 2. Recruiter availability is a quick win.
> 3. Medicine needs pickup within the refill window.
>
> Everything else can wait.

## Workflow 3: Cleanup

User:

> Clean up my open loops.

System:

> I found 18 open loops.
>
> My recommendation:
> - close 2 that look done
> - archive 6 stale ideas
> - keep 7 active
> - review 3 that need your call
>
> I’ll start with the 3 uncertain ones.

## Workflow 4: Avoidance Detection

System:

> You marked supplement research as important three weeks ago, but deferred it 8 times.
>
> Pattern says this is either not important or too vague.
>
> Recommendation: archive it unless you want me to turn it into a 10-minute research brief.

## Workflow 5: Prepared Action

User:

> I need to send my availability to the recruiter.

System:

> Drafted it. I can use your personal calendar, but I do not have your work calendar. Review these times before send.

## Workflow 6: Momentum Push

System:

> You’re treating this like a big task, but the actual next step is small.
>
> Send availability. Estimated effort: 3 minutes.
>
> Do that first. Then decide whether to keep applying today.

## Workflow 7: Recalibration

System:

> You’ve repeatedly marked research loops as important but rarely act on them.
>
> New default suggestion: I’ll keep research ideas warm instead of active unless they have a deadline or you explicitly say they matter this week.

## Workflow 8: User Correction

User:

> I already picked up the medicine.

System:

> Good. I’ll close that loop. Roughly when did you do it?

If user answers, update history. If not, close with approximate current time and low confidence.

---

# 32. Initial Scope

Build the smallest useful version.

Must have:

- conversational capture
- loop extraction
- multiple loops from one message
- loop state model
- timestamps
- open loops view
- cleanup mode
- basic resurfacing
- basic memory/preferences
- basic duplicate detection
- basic context linking
- ability to complete/archive/delete/abandon loops
- ability to show history/archive
- ability to undo or restore recent automatic cleanup
- direct, non-generic tone
- simple prepared next actions

Should have soon:

- effort estimates
- stale-loop detection
- repeated-deferral detection
- quick-win identification
- “what am I missing?” interaction
- “what matters today?” interaction
- “quiz me on what’s open” interaction
- basic pattern memory

Defer initially:

- full external integrations
- autonomous purchases
- job application submission
- medical/legal/financial/government submissions
- complex multi-agent architecture
- advanced mobile polish
- family sharing
- enterprise workspace features
- complex notification system
- large settings UI
- advanced personality designer
- every possible connector

---

# 33. Build Simplicity Guidance

Do not build the full long-term architecture on day one.

But preserve these foundations:

- loops must be first-class objects
- messages must not be the canonical source of truth
- timestamps must be first-class
- loop state must be explicit
- memory must be conceptually separable
- actions must have risk/autonomy policy
- cleanup must be first-class
- undo/review must exist for trust
- context linking must be possible
- preferences and patterns must be able to evolve
- user-facing complexity must stay low

Avoid premature complexity such as:

- elaborate agent hierarchies
- abstract frameworks with no immediate user value
- overly granular lifecycle states
- complex dashboards
- extensive settings panels
- speculative integrations
- trying to solve every domain immediately

The MVP should feel like a simple app that already understands the product philosophy.

---

# 34. Ambiguities to Handle Carefully

## Assistant vs Not Assistant

The product behaves like an assistant in some ways, but should not be framed as one.

Avoid assistant tropes.

Focus on mental load, loops, and follow-through.

## Accountability vs Support

Some users want direct accountability. Others do not.

Do not bake in a single tone.

Initial tone can be direct, but tone must become adaptive.

## Memory vs Hoarding

The system should remember enough to maintain continuity, but not hold everything active forever.

The goal is useful continuity, not perfect recall.

## Autonomy vs Safety

Approval for every action makes the user a manager.

Silent action on consequential things is unsafe.

Use delegated authority, reversibility, review, and risk levels.

## Cleanup vs Overwhelm

Do not show giant unresolved lists without guidance.

Always suggest a cleanup path.

## Broad Vision vs Narrow Wedge

The long-term vision is broad, but the first version should focus on unresolved intent capture, resurfacing, cleanup, and closure.

Do not start by building an everything app.

## Conversation vs Structure

The user should mostly experience conversation.

But internally, the product needs structured loops and memory.

Do not let conversational UI prevent structured state.

## Personal Life vs Professional Life

The first version is personal-life oriented.

It may support work loops because users have them, but do not frame the product as a workplace tool.

---

# 35. Quality Bar

The product is working if the user says:

- I stopped carrying this mentally.
- It knew what mattered.
- It helped me decide.
- It did not make me repeat myself.
- It reminded me without spamming me.
- It helped me close things I was avoiding.
- It helped me let go of things I no longer cared about.
- It made my life feel more manageable.
- It did obvious prep work without making me micromanage it.
- I trust it enough to dump thoughts into it.

The product is failing if the user says:

- I have to manage another app.
- It nags me.
- It forgets context.
- It makes me repeat myself.
- It asks permission for obvious internal actions.
- It does consequential things I did not want.
- It keeps junk active forever.
- It feels like a to-do app.
- It feels like ChatGPT with reminders.
- It feels like a productivity dashboard.
- It creates more mental load than it removes.

---

# 36. Final Product Principle

The app should behave like a competent familiar helper managing delegated cognitive clutter:

- capture messy input
- infer what matters
- preserve context
- organize loops
- prepare next actions
- resurface intelligently
- challenge stale intent
- clean up clutter
- respect delegated authority
- avoid notification spam
- keep records
- learn from correction
- help the user close or release loops

Final internal mantra:

> Dump it. Defrag it. Resurface what matters. Close the loop.

Final consumer promise:

> A place to put the stuff you keep meaning to do, so you can stop carrying it in your head.
