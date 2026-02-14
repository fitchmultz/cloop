import { and, desc, eq, not, sql } from "drizzle-orm";
import { db, schema } from "@/db";

export async function getSnapshot() {
  "use cache";

  const [missionRow] = await db.select().from(schema.meta).where(eq(schema.meta.key, "mission"));
  const [guardrailsRow] = await db
    .select()
    .from(schema.meta)
    .where(eq(schema.meta.key, "guardrails"));
  const [lastUpdatedRow] = await db
    .select()
    .from(schema.meta)
    .where(eq(schema.meta.key, "last_updated"));

  const mission = missionRow?.valueJson ? JSON.parse(missionRow.valueJson) : {};
  const guardrails = guardrailsRow?.valueJson ? JSON.parse(guardrailsRow.valueJson) : {};
  const lastUpdated = lastUpdatedRow?.valueJson || new Date().toISOString();

  const tasks = await db.select().from(schema.tasks).orderBy(schema.tasks.sortIndex);

  const nextActions = await db
    .select()
    .from(schema.nextActions)
    .orderBy(schema.nextActions.sortIndex);

  const recentlyDone = await db
    .select()
    .from(schema.recentlyDone)
    .orderBy(schema.recentlyDone.sortIndex);

  const weeklyScorecard = await db
    .select()
    .from(schema.weeklyScorecard)
    .orderBy(schema.weeklyScorecard.sortIndex);

  const sessionLog = await db.select().from(schema.sessionLog).orderBy(schema.sessionLog.sortIndex);

  const pipelineActive = await db
    .select()
    .from(schema.jobs)
    .orderBy(
      sql`CASE WHEN priority GLOB 'P[0-9]*' THEN CAST(SUBSTR(priority, 2) AS INTEGER) ELSE 99 END`,
      sql`CASE WHEN due GLOB '____-__-__' THEN due ELSE '9999-12-31' END`,
      schema.jobs.company,
      schema.jobs.role
    );

  const criticalClaims = await db
    .select()
    .from(schema.criticalClaims)
    .orderBy(schema.criticalClaims.claimId);

  const claimChecks = await db
    .select()
    .from(schema.claimChecks)
    .orderBy(desc(schema.claimChecks.checkId))
    .limit(10);

  const outreachQueue = await db
    .select()
    .from(schema.outreach)
    .orderBy(
      sql`CASE WHEN LOWER(status) = 'blocked' THEN 1 ELSE 0 END`,
      sql`CASE WHEN send_date GLOB '____-__-__' THEN send_date ELSE '9999-12-31' END`,
      sql`CASE WHEN id GLOB 'O[0-9]*' THEN CAST(SUBSTR(id, 2) AS INTEGER) ELSE 9999 END`
    );

  return {
    lastUpdated,
    mission,
    guardrails,
    nextActions,
    tasks,
    recentlyDone,
    weeklyScorecard,
    sessionLog,
    pipelineActive,
    criticalClaims,
    claimChecks,
    outreachQueue,
  };
}

export async function getActivePipeline() {
  "use cache";

  const jobs = await db
    .select()
    .from(schema.jobs)
    .where(and(not(eq(schema.jobs.stage, "Blocked")), not(eq(schema.jobs.stage, "Unverified"))))
    .orderBy(schema.tasks.sortIndex);

  return jobs;
}

export async function getBlockedPipeline() {
  "use cache";

  return db.select().from(schema.jobs).where(eq(schema.jobs.stage, "Blocked"));
}

export async function getOutreachQueue() {
  "use cache";

  return db
    .select()
    .from(schema.outreach)
    .orderBy(desc(schema.outreach.priority));
}

export async function getTasks() {
  "use cache";

  return db.select().from(schema.tasks).orderBy(schema.tasks.sortIndex);
}

export async function getCriticalClaims() {
  "use cache";

  return db.select().from(schema.criticalClaims).orderBy(schema.criticalClaims.claimId);
}

export async function getSessionLog(limit = 15) {
  "use cache";

  return db
    .select()
    .from(schema.sessionLog)
    .orderBy(desc(schema.sessionLog.sortIndex))
    .limit(limit);
}

export async function getMetrics() {
  "use cache";

  const allJobs = await db.select().from(schema.jobs);
  const allTasks = await db.select().from(schema.tasks);
  const allOutreach = await db.select().from(schema.outreach);

  const stageCounts = {
    ready: allJobs.filter((j) => j.stage === "Ready-Apply").length,
    conditional: allJobs.filter((j) => j.stage === "Conditional-Apply").length,
    blocked: allJobs.filter((j) => j.stage === "Blocked").length,
    unverified: allJobs.filter((j) => j.stage === "Unverified").length,
    applied: allJobs.filter((j) => j.stage === "Applied").length,
    interviewing: allJobs.filter((j) => j.stage === "Interviewing").length,
    offer: allJobs.filter((j) => j.stage === "Offer").length,
  };

  const p0Queue = allJobs.filter(
    (j) => j.priority === "P0" && ["Ready-Apply", "Conditional-Apply"].includes(j.stage)
  ).length;

  const p1Queue = allJobs.filter(
    (j) => j.priority === "P1" && ["Ready-Apply", "Conditional-Apply"].includes(j.stage)
  ).length;

  const taskCounts = {
    pending: allTasks.filter((t) => t.status.toLowerCase() === "pending").length,
    inProgress: allTasks.filter((t) =>
      ["in progress", "in_progress"].includes(t.status.toLowerCase())
    ).length,
    blocked: allTasks.filter((t) => t.status.toLowerCase() === "blocked").length,
    done: allTasks.filter((t) => ["done", "completed", "complete"].includes(t.status.toLowerCase()))
      .length,
  };

  const outreachCounts = {
    pending: allOutreach.filter((o) => o.status.toLowerCase() === "pending").length,
    applied: allOutreach.filter((o) => o.status.toLowerCase() === "applied").length,
    blocked: allOutreach.filter((o) => o.status.toLowerCase() === "blocked").length,
  };

  return {
    stageCounts,
    p0Queue,
    p1Queue,
    taskCounts,
    outreachCounts,
    totalJobs: allJobs.length,
    totalTasks: allTasks.length,
    totalOutreach: allOutreach.length,
  };
}
