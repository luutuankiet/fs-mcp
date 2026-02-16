# GSD-Lite Inbox


## How to Use

- Capture immediately when loop discovered
- Assign next LOOP-NNN ID (increment from last ID in this file)
- Write context-rich entry (not just a title - tell the story)
- Don't interrupt current task to address loop
- Review at phase end for next phase planning
- User can reference by ID: "discuss LOOP-007"

---

## Active Loops


### [EXAMPLE-LOOP-001] - Client update workflow needs pull mechanism - Status: Open
**Created:** 2026-01-23 | **Source:** During PHASE-001 planning | **Origin:** User

**Context:**
While discussing the initial architecture for the sync service, user raised a concern about how clients would receive updates. The current design only handles push from server, but user's mental model includes scenarios where clients might be offline and need to catch up.

**Details:**
The `SyncService` class in `src/services/sync.ts:45-78` currently implements `pushUpdate()` but has no corresponding pull mechanism. User specifically mentioned:
> "What happens when a client reconnects after being offline for 2 hours? They'd miss all the updates."

This affects the `ClientConnection` interface at `src/types/client.ts:12` which assumes always-connected clients. Need to decide:
1. Do we add a `pullUpdates(since: timestamp)` method?
2. Or implement message queuing per-client?
3. What's the retention window for missed updates?

**Resolution:** _(pending)_

---

### [EXAMPLE-LOOP-002] - Token expiry strategy unclear for long-running sessions - Status: Clarifying
**Created:** 2026-01-23 | **Source:** During TASK-AUTH-001 implementation | **Origin:** Agent

**Context:**
While implementing JWT generation in `src/auth/token.ts`, agent discovered an ambiguity in the requirements. The spec says "tokens should expire" but doesn't specify duration or refresh strategy. This matters because the dashboard is designed for long work sessions (4-8 hours).

**Details:**
Current implementation at `src/auth/token.ts:23-31`:
```typescript
export function generateToken(userId: string): string {
  return jwt.sign(
    { sub: userId, iat: Date.now() },
    process.env.JWT_SECRET,
    { expiresIn: '???' }  // <-- What should this be?
  );
}
```

Options discovered during research:
- Short-lived (15min) + refresh token: More secure, but adds complexity
- Long-lived (24h): Simpler, but security concern if token leaked
- Sliding window: Token refreshes on activity, expires on idle

User preference needed. This blocks finalizing the auth implementation.

**Resolution:** _(awaiting user input)_

---

### [EXAMPLE-LOOP-003] - Database migration strategy for production - Status: Open
**Created:** 2026-01-24 | **Source:** During TASK-DB-002 schema design | **Origin:** Agent

**Context:**
Agent completed the initial schema design in `prisma/schema.prisma`, but realized there's no migration strategy defined for when we deploy to production. The current approach uses `prisma db push` which is fine for development but destructive in production.

**Details:**
The schema includes relationships that require careful migration ordering:
```prisma
// prisma/schema.prisma:34-45
model User {
  id        String   @id @default(uuid())
  posts     Post[]   // Has-many relationship
  profile   Profile? // Optional one-to-one
}

model Post {
  authorId  String
  author    User @relation(fields: [authorId], references: [id])
}
```

If we add a NOT NULL column to `User` later, existing rows will fail. Need to establish:
1. Migration file naming convention
2. Rollback strategy
3. CI/CD pipeline integration for migrations
4. Data backfill approach for schema changes

This isn't blocking current work but will become critical before first production deploy.

**Resolution:** _(to be addressed in PHASE-003)_

---

## Resolved Loops

### [EXAMPLE-LOOP-004] - Password reset flow scope unclear - Status: Resolved
**Created:** 2026-01-22 | **Source:** During TASK-002 user discussion | **Origin:** User

**Context:**
User mentioned "we should add password reset" during a planning session for the auth module. It was unclear whether this was a Phase 1 requirement or a future nice-to-have. User's exact words: "Add password reset flow... actually, maybe later?"

**Details:**
Password reset would require:
- New API endpoint: `POST /auth/reset-request`
- Email service integration (not currently in scope)
- Reset token table in database
- Frontend reset flow (2 new pages minimum)

This represented significant scope creep if included in Phase 1.

**Resolution:**
Discussed with user on 2026-01-23. Decision: Password reset is PHASE-002 scope. Created TASK-PWD-001 in phase 2 planning. User confirmed: "Yes, let's ship basic auth first, reset flow can wait."

Logged as `[LOG-025] - [DECISION]` in WORK.md.

---

### [EXAMPLE-LOOP-005] - Profile page data model needs user input - Status: Resolved
**Created:** 2026-01-22 | **Source:** During TASK-003 component design | **Origin:** Agent

**Context:**
While designing the `ProfileCard` component, agent needed to know what user data to display. The `User` model had basic fields but it was unclear if profile should show activity history, badges, or social links.

**Details:**
Original `User` model at `src/models/user.ts:5-12`:
```typescript
interface User {
  id: string;
  email: string;
  name: string;
  createdAt: Date;
  // What else goes here for profile display?
}
```

Agent prepared three options:
1. Minimal: Just name + avatar + join date
2. Social: Add bio, social links, website
3. Gamified: Add badges, activity streak, contribution count

**Resolution:**
User chose Option 2 (Social) on 2026-01-23. Extended interface to include `bio`, `avatarUrl`, `socialLinks`. Implementation completed in TASK-003.

---

*Review active loops before each phase promotion. Resolve or carry forward intentionally.*
