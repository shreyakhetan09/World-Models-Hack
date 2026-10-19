// Mints a short-lived, scoped Reactor JWT so the API key never reaches the browser.

const MODEL = "reactor/lingbot-world-2";

export async function POST() {
  const apiKey = process.env.REACTOR_API_KEY;
  if (!apiKey) {
    return Response.json({ error: "REACTOR_API_KEY is not set in frontend/.env.local" }, { status: 503 });
  }

  const res = await fetch("https://api.reactor.inc/tokens", {
    method: "POST",
    headers: { "Reactor-API-Key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      expires_after: 3600,
      authorization_details: [
        {
          type: "session",
          resources: { models: { match: [MODEL] } },
          // Counts every session this token ever creates, not just concurrent ones.
          constraints: { max_sessions: 50, max_session_duration_seconds: 1800 },
        },
      ],
    }),
  });

  if (!res.ok) {
    const detail = await res.text();
    return Response.json({ error: `Reactor token request failed (${res.status})`, detail }, { status: 502 });
  }
  const { jwt, expires_at } = await res.json();
  return Response.json({ jwt, expires_at }, { headers: { "Cache-Control": "private, no-store" } });
}
