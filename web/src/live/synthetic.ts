/** The synthetic journey's line among the worker's jobs (plan UX, A2). */
import type { JobHealth } from "@/lib/api/v1/types";

export const SYNTHETIC_JOB = "synthetic_journey";

/** Its line, or null while the worker has never run it (it is off until the owner configures it). */
export function syntheticJob(jobs: readonly JobHealth[]): JobHealth | null {
  return jobs.find((j) => j.job_type === SYNTHETIC_JOB) ?? null;
}
