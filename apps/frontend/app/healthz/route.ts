// Lightweight liveness probe for the container health check (does not touch the backend).
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" });
}
