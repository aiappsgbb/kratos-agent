#!/usr/bin/env node
// m365-graph-mcp-server — stdio MCP server that mocks the Microsoft Graph
// surface against curated JSON fixtures. Tools cover users + presence,
// mailbox search and read, calendar events, OneDrive/SharePoint files,
// and Teams chats. Writes are two-step: draft_message + send_message,
// create_event etc. mutate in-memory state for the lifetime of the
// process so multi-turn demos see consistent results.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(here, "data");

// ── Types ─────────────────────────────────────────────────────────────────

type Presence = "Available" | "Busy" | "DoNotDisturb" | "Away" | "BeRightBack" | "Offline";

type User = {
  id: string;
  employee_id: string;
  azure_ad_object_id: string;
  userPrincipalName: string;
  displayName: string;
  givenName: string;
  surname: string;
  mail: string;
  jobTitle: string;
  department: string;
  officeLocation: string;
  mobilePhone: string;
  manager_id: string | null;
  accountEnabled: boolean;
  presence: Presence;
  presence_activity: string;
  ooo_enabled: boolean;
  ooo_message: string | null;
};

type Recipient = { emailAddress: { name: string; address: string } };
type Flag = { flagStatus: "flagged" | "notFlagged" | "complete" };
type Message = {
  id: string;
  conversationId: string;
  from: Recipient;
  toRecipients: Recipient[];
  ccRecipients?: Recipient[];
  subject: string;
  bodyPreview: string;
  body: string;
  receivedDateTime: string;
  importance: "low" | "normal" | "high";
  hasAttachments: boolean;
  categories: string[];
  mailbox: string;
  folder: "Inbox" | "Sent Items" | "Drafts" | "Archive";
  isRead: boolean;
  flag: Flag;
};

type AttendeeStatus = { response: "none" | "organizer" | "tentative" | "accepted" | "declined" };
type Attendee = { emailAddress: { name: string; address: string }; type: "required" | "optional"; status: AttendeeStatus };
type Event = {
  id: string;
  subject: string;
  organizer: Recipient;
  attendees: Attendee[];
  start: { dateTime: string; timeZone: string };
  end:   { dateTime: string; timeZone: string };
  location: { displayName: string };
  isOnlineMeeting: boolean;
  categories: string[];
  showAs: "free" | "tentative" | "busy" | "oof" | "workingElsewhere";
  mailbox: string;
  bodyPreview: string;
};

type ShareGrant = { user: { id: string; displayName: string }; permission: "read" | "read-write" };
type DriveFile = {
  id: string;
  name: string;
  webUrl: string;
  drive: "onedrive" | "sharepoint";
  site: string;
  path: string;
  size: number;
  mimeType: string;
  createdBy: { user: { id: string; displayName: string } };
  createdDateTime: string;
  lastModifiedBy: { user: { id: string; displayName: string } };
  lastModifiedDateTime: string;
  sharedWith: ShareGrant[];
  contentSummary: string;
};

type ChatMember = { id: string; displayName: string };
type ChatMessage = {
  id: string;
  from: { user: { id: string; displayName: string } };
  createdDateTime: string;
  body: { content: string };
  mentions: { id: number; mentionText: string; mentioned: { user: { id: string } } }[];
};
type Chat = {
  id: string;
  topic: string;
  chatType: "oneOnOne" | "channel" | "group";
  team?: string;
  channel?: string;
  members: ChatMember[];
  lastUpdatedDateTime: string;
  messages: ChatMessage[];
};

// ── Load fixtures into mutable in-memory store ────────────────────────────

const load = <T>(file: string): T =>
  JSON.parse(readFileSync(path.join(dataDir, file), "utf-8")) as T;

const users:    User[]      = load("users.json");
const messages: Message[]   = load("messages.json");
const events:   Event[]     = load("events.json");
const files:    DriveFile[] = load("files.json");
const chats:    Chat[]      = load("chats.json");

// Per-process ID counters so writes generate plausible ids that don't
// collide with the seeded fixtures.
let nextMsgSeq = 39000;
let nextEvtSeq = 49000;

// ── Helpers ───────────────────────────────────────────────────────────────

const text = (obj: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(obj, null, 2) }],
});
const notFound = (kind: string, id: string) => ({
  content: [{ type: "text" as const, text: JSON.stringify({ error: "not_found", kind, id }) }],
  isError: true,
});
const validationError = (msg: string, details?: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify({ error: "validation_error", message: msg, details: details ?? null }) }],
  isError: true,
});

const findUser = (selector: string): User | undefined => {
  const s = selector.toLowerCase();
  return users.find(
    (u) =>
      u.id.toLowerCase() === s ||
      u.employee_id.toLowerCase() === s ||
      u.userPrincipalName.toLowerCase() === s ||
      u.mail.toLowerCase() === s ||
      u.azure_ad_object_id.toLowerCase() === s
  );
};

const summariseMessage = (m: Message) => ({
  id: m.id,
  conversationId: m.conversationId,
  from: m.from.emailAddress,
  to: (m.toRecipients ?? []).map((r) => r.emailAddress),
  cc: (m.ccRecipients ?? []).map((r) => r.emailAddress),
  subject: m.subject,
  bodyPreview: m.bodyPreview,
  receivedDateTime: m.receivedDateTime,
  importance: m.importance,
  hasAttachments: m.hasAttachments,
  isRead: m.isRead,
  flagged: m.flag.flagStatus === "flagged",
  categories: m.categories,
  mailbox: m.mailbox,
  folder: m.folder,
});

const summariseEvent = (e: Event) => ({
  id: e.id,
  subject: e.subject,
  organizer: e.organizer.emailAddress,
  start: e.start,
  end: e.end,
  location: e.location.displayName,
  isOnlineMeeting: e.isOnlineMeeting,
  showAs: e.showAs,
  attendeeCount: e.attendees.length,
  categories: e.categories,
  mailbox: e.mailbox,
});

const summariseFile = (f: DriveFile) => ({
  id: f.id,
  name: f.name,
  webUrl: f.webUrl,
  drive: f.drive,
  site: f.site,
  path: f.path,
  size: f.size,
  mimeType: f.mimeType,
  lastModifiedBy: f.lastModifiedBy.user.displayName,
  lastModifiedDateTime: f.lastModifiedDateTime,
  sharedWithCount: f.sharedWith.length,
  contentSummary: f.contentSummary,
});

const summariseChat = (c: Chat) => ({
  id: c.id,
  topic: c.topic,
  chatType: c.chatType,
  team: c.team ?? null,
  channel: c.channel ?? null,
  members: c.members,
  lastUpdatedDateTime: c.lastUpdatedDateTime,
  messageCount: c.messages.length,
});

// ── Server ────────────────────────────────────────────────────────────────

const server = new McpServer({
  name: "m365-graph-mcp-server",
  version: "0.1.0",
});

// ── Users + presence ──────────────────────────────────────────────────────

server.registerTool(
  "m365_list_users",
  {
    title: "List users",
    description:
      "List directory users with optional filters. Use department/manager_id to scope a team; " +
      "use accountEnabled=false to find deactivated accounts.",
    inputSchema: {
      department: z.string().optional().describe("Substring match on Workday department (e.g. 'Engineering')."),
      manager_id: z.string().optional().describe("Direct reports of an EMP-* id."),
      accountEnabled: z.boolean().optional(),
    },
  },
  async ({ department, manager_id, accountEnabled }) => {
    let pool = users;
    if (department) {
      const d = department.toLowerCase();
      pool = pool.filter((u) => u.department.toLowerCase().includes(d));
    }
    if (manager_id) pool = pool.filter((u) => u.manager_id === manager_id);
    if (accountEnabled !== undefined) pool = pool.filter((u) => u.accountEnabled === accountEnabled);
    return text({ users: pool, total: pool.length });
  }
);

server.registerTool(
  "m365_get_user",
  {
    title: "Get one user",
    description:
      "Look up a user by EMP-* id, userPrincipalName, mail, or azure_ad_object_id. " +
      "Returns the full directory record including presence and OOO state.",
    inputSchema: {
      selector: z.string().describe("EMP-* id, UPN, mail, or AAD object id."),
    },
  },
  async ({ selector }) => {
    const u = findUser(selector);
    return u ? text(u) : notFound("user", selector);
  }
);

server.registerTool(
  "m365_get_user_presence",
  {
    title: "Get user presence + OOO",
    description: "Return live presence, activity, and the auto-reply message if OOO is on.",
    inputSchema: {
      selector: z.string().describe("EMP-* id, UPN, mail, or AAD object id."),
    },
  },
  async ({ selector }) => {
    const u = findUser(selector);
    if (!u) return notFound("user", selector);
    return text({
      id: u.id,
      displayName: u.displayName,
      presence: u.presence,
      activity: u.presence_activity,
      ooo: u.ooo_enabled
        ? { enabled: true, message: u.ooo_message }
        : { enabled: false, message: null },
    });
  }
);

// ── Mail ─────────────────────────────────────────────────────────────────

server.registerTool(
  "m365_search_messages",
  {
    title: "Search mailbox messages",
    description:
      "Search a user's mailbox. At minimum the mailbox owner must be specified. " +
      "Combine filters freely; unread/flagged/importance default to no-filter. " +
      "Returns lightweight message summaries; use m365_get_message for the full body.",
    inputSchema: {
      mailbox: z.string().describe("Mailbox owner: EMP-* id, UPN, or mail."),
      query: z.string().optional().describe("Substring search across subject + bodyPreview + from/to addresses."),
      folder: z.enum(["Inbox", "Sent Items", "Drafts", "Archive"]).optional(),
      from_date: z.string().optional().describe("ISO datetime, inclusive lower bound on receivedDateTime."),
      to_date: z.string().optional().describe("ISO datetime, inclusive upper bound on receivedDateTime."),
      importance: z.enum(["low", "normal", "high"]).optional(),
      flagged_only: z.boolean().optional(),
      unread_only: z.boolean().optional(),
      category: z.string().optional().describe("Match a single category tag exactly."),
      limit: z.number().int().min(1).max(100).optional(),
    },
  },
  async ({ mailbox, query, folder, from_date, to_date, importance, flagged_only, unread_only, category, limit }) => {
    const owner = findUser(mailbox);
    if (!owner) return notFound("mailbox", mailbox);
    let pool = messages.filter((m) => m.mailbox === owner.id);
    if (folder) pool = pool.filter((m) => m.folder === folder);
    if (importance) pool = pool.filter((m) => m.importance === importance);
    if (flagged_only) pool = pool.filter((m) => m.flag.flagStatus === "flagged");
    if (unread_only) pool = pool.filter((m) => !m.isRead);
    if (category) pool = pool.filter((m) => m.categories.includes(category));
    if (from_date) pool = pool.filter((m) => m.receivedDateTime >= from_date);
    if (to_date)   pool = pool.filter((m) => m.receivedDateTime <= to_date);
    if (query) {
      const q = query.toLowerCase();
      pool = pool.filter(
        (m) =>
          m.subject.toLowerCase().includes(q) ||
          m.bodyPreview.toLowerCase().includes(q) ||
          m.body.toLowerCase().includes(q) ||
          m.from.emailAddress.address.toLowerCase().includes(q) ||
          m.from.emailAddress.name.toLowerCase().includes(q) ||
          (m.toRecipients ?? []).some((r) => r.emailAddress.address.toLowerCase().includes(q)) ||
          (m.ccRecipients ?? []).some((r) => r.emailAddress.address.toLowerCase().includes(q))
      );
    }
    pool = [...pool].sort((a, b) => b.receivedDateTime.localeCompare(a.receivedDateTime));
    return text({
      messages: pool.slice(0, limit ?? 25).map(summariseMessage),
      total: pool.length,
      mailbox: { id: owner.id, displayName: owner.displayName, mail: owner.mail },
    });
  }
);

server.registerTool(
  "m365_get_message",
  {
    title: "Get one message (full body)",
    description: "Fetch a single message by id including the full body and recipient list.",
    inputSchema: { message_id: z.string().describe("Message id, e.g. MSG-30001.") },
  },
  async ({ message_id }) => {
    const m = messages.find((x) => x.id === message_id);
    return m ? text(m) : notFound("message", message_id);
  }
);

server.registerTool(
  "m365_get_thread",
  {
    title: "Get a conversation thread",
    description: "Return every message sharing a conversationId, ordered oldest → newest.",
    inputSchema: { conversation_id: z.string().describe("Conversation id, e.g. CONV-301.") },
  },
  async ({ conversation_id }) => {
    const thread = messages
      .filter((m) => m.conversationId === conversation_id)
      .sort((a, b) => a.receivedDateTime.localeCompare(b.receivedDateTime));
    if (thread.length === 0) return notFound("conversation", conversation_id);
    return text({ conversation_id, messages: thread, total: thread.length });
  }
);

server.registerTool(
  "m365_draft_message",
  {
    title: "Create a Draft message",
    description:
      "Create a Draft (in the sender's Drafts folder) — does NOT send. Use this to prepare an email " +
      "for human-in-the-loop confirmation before m365_send_message promotes it to Sent Items.",
    inputSchema: {
      from: z.string().describe("Sender: EMP-* id, UPN, or mail."),
      to:   z.array(z.string()).min(1).describe("Recipient email addresses."),
      cc:   z.array(z.string()).optional(),
      subject: z.string().min(1),
      body: z.string().min(1).describe("Plain-text or markdown body."),
      importance: z.enum(["low", "normal", "high"]).optional(),
      reply_to_message_id: z.string().optional().describe("If set, threads onto an existing conversationId."),
    },
  },
  async ({ from, to, cc, subject, body, importance, reply_to_message_id }) => {
    const sender = findUser(from);
    if (!sender) return notFound("user", from);
    let conversationId = `CONV-${39000 + (nextMsgSeq - 39000)}`;
    if (reply_to_message_id) {
      const parent = messages.find((m) => m.id === reply_to_message_id);
      if (!parent) return notFound("message", reply_to_message_id);
      conversationId = parent.conversationId;
    }
    const newMsg: Message = {
      id: `MSG-${nextMsgSeq++}`,
      conversationId,
      from: { emailAddress: { name: sender.displayName, address: sender.mail } },
      toRecipients: to.map((addr) => ({ emailAddress: { name: addr.split("@")[0], address: addr } })),
      ccRecipients: (cc ?? []).map((addr) => ({ emailAddress: { name: addr.split("@")[0], address: addr } })),
      subject,
      bodyPreview: body.slice(0, 220),
      body,
      receivedDateTime: new Date().toISOString(),
      importance: importance ?? "normal",
      hasAttachments: false,
      categories: [],
      mailbox: sender.id,
      folder: "Drafts",
      isRead: true,
      flag: { flagStatus: "notFlagged" },
    };
    messages.push(newMsg);
    return text({ draft: newMsg, note: "Draft created in sender's Drafts folder — not sent. Promote with m365_send_message." });
  }
);

server.registerTool(
  "m365_send_message",
  {
    title: "Send a Draft message",
    description:
      "Promote an existing Draft message to Sent Items (moves the message and stamps receivedDateTime). " +
      "Strict H-I-T-L: the agent MUST show the Draft to the user and get explicit confirmation before calling this.",
    inputSchema: { message_id: z.string().describe("Id of the Draft to send.") },
  },
  async ({ message_id }) => {
    const m = messages.find((x) => x.id === message_id);
    if (!m) return notFound("message", message_id);
    if (m.folder !== "Drafts") return validationError(`message ${message_id} is in ${m.folder}, only Drafts can be sent`);
    m.folder = "Sent Items";
    m.receivedDateTime = new Date().toISOString();
    return text({ sent: m, receipt: `Sent: ${m.id} · ${m.subject} · to ${m.toRecipients.map((r) => r.emailAddress.address).join(", ")}` });
  }
);

// ── Calendar ─────────────────────────────────────────────────────────────

server.registerTool(
  "m365_list_events",
  {
    title: "List calendar events",
    description: "Calendar events for a mailbox in an inclusive date range.",
    inputSchema: {
      mailbox: z.string().describe("Mailbox owner: EMP-* id, UPN, or mail."),
      from_date: z.string().describe("ISO date or datetime, inclusive."),
      to_date: z.string().describe("ISO date or datetime, inclusive."),
      category: z.string().optional(),
      showAs: z.enum(["free", "tentative", "busy", "oof", "workingElsewhere"]).optional(),
    },
  },
  async ({ mailbox, from_date, to_date, category, showAs }) => {
    const owner = findUser(mailbox);
    if (!owner) return notFound("mailbox", mailbox);
    const fromIso = from_date.length === 10 ? from_date + "T00:00:00" : from_date;
    const toIso   = to_date.length   === 10 ? to_date   + "T23:59:59" : to_date;
    let pool = events.filter(
      (e) => e.mailbox === owner.id && e.start.dateTime <= toIso && e.end.dateTime >= fromIso
    );
    if (category) pool = pool.filter((e) => e.categories.includes(category));
    if (showAs) pool = pool.filter((e) => e.showAs === showAs);
    pool = [...pool].sort((a, b) => a.start.dateTime.localeCompare(b.start.dateTime));
    return text({
      events: pool.map(summariseEvent),
      total: pool.length,
      mailbox: { id: owner.id, displayName: owner.displayName },
    });
  }
);

server.registerTool(
  "m365_get_event",
  {
    title: "Get one calendar event (full)",
    description: "Fetch a single event by id including the full attendee list and response status.",
    inputSchema: { event_id: z.string().describe("Event id, e.g. EVT-40001.") },
  },
  async ({ event_id }) => {
    const e = events.find((x) => x.id === event_id);
    return e ? text(e) : notFound("event", event_id);
  }
);

server.registerTool(
  "m365_find_meeting_times",
  {
    title: "Find common free slots",
    description:
      "Given a list of attendees and a date window, return 30-minute slots in working hours " +
      "(09:00-17:00 in the requested timezone) where no attendee has a busy/oof event on their calendar.",
    inputSchema: {
      attendees: z.array(z.string()).min(1).describe("Attendees: EMP-* ids, UPNs, or mail addresses."),
      from_date: z.string().describe("ISO date (YYYY-MM-DD), inclusive."),
      to_date: z.string().describe("ISO date (YYYY-MM-DD), inclusive."),
      duration_minutes: z.number().int().min(15).max(240).optional().describe("Slot length (default 30)."),
      max_slots: z.number().int().min(1).max(20).optional(),
    },
  },
  async ({ attendees, from_date, to_date, duration_minutes, max_slots }) => {
    const resolved = attendees.map((a) => findUser(a));
    const missing = attendees.filter((_, i) => !resolved[i]);
    if (missing.length > 0) return validationError("unresolved attendees", missing);
    const ownerIds = new Set(resolved.map((u) => u!.id));
    const duration = (duration_minutes ?? 30) * 60_000;
    const slots: { start: string; end: string }[] = [];
    // Walk days in window; slot grid every 30 minutes.
    const start = new Date(from_date + "T00:00:00");
    const stop  = new Date(to_date   + "T23:59:59");
    for (let d = new Date(start); d <= stop; d.setUTCDate(d.getUTCDate() + 1)) {
      for (let hour = 9; hour < 17; hour++) {
        for (const minute of [0, 30]) {
          const slotStart = new Date(d);
          slotStart.setUTCHours(hour, minute, 0, 0);
          const slotEnd = new Date(slotStart.getTime() + duration);
          if (slotEnd.getUTCHours() > 17 || (slotEnd.getUTCHours() === 17 && slotEnd.getUTCMinutes() > 0)) continue;
          const slotStartIso = slotStart.toISOString().slice(0, 19);
          const slotEndIso   = slotEnd.toISOString().slice(0, 19);
          const conflict = events.some((e) => {
            if (!ownerIds.has(e.mailbox)) return false;
            if (e.showAs === "free") return false;
            return e.start.dateTime < slotEndIso && e.end.dateTime > slotStartIso;
          });
          if (!conflict) {
            slots.push({ start: slotStartIso, end: slotEndIso });
            if (slots.length >= (max_slots ?? 8)) {
              return text({ slots, attendees: resolved.map((u) => u!.displayName) });
            }
          }
        }
      }
    }
    return text({ slots, attendees: resolved.map((u) => u!.displayName) });
  }
);

server.registerTool(
  "m365_create_event",
  {
    title: "Create a calendar event",
    description:
      "Schedule a new event on the organizer's calendar with attendees in response=none state. " +
      "Strict H-I-T-L: the agent MUST show the proposed event to the user and get explicit " +
      "confirmation before calling this.",
    inputSchema: {
      organizer: z.string().describe("EMP-* id, UPN, or mail of the organizer."),
      subject: z.string().min(1),
      attendees: z.array(
        z.object({
          email: z.string(),
          type: z.enum(["required", "optional"]).optional(),
        })
      ).min(1),
      start_iso: z.string().describe("ISO local datetime (no offset)."),
      end_iso: z.string().describe("ISO local datetime (no offset)."),
      timezone: z.string().optional().describe("Defaults to America/New_York."),
      location: z.string().optional(),
      is_online_meeting: z.boolean().optional(),
      body_preview: z.string().optional(),
    },
  },
  async ({ organizer, subject, attendees, start_iso, end_iso, timezone, location, is_online_meeting, body_preview }) => {
    const org = findUser(organizer);
    if (!org) return notFound("user", organizer);
    if (start_iso >= end_iso) return validationError("end_iso must be after start_iso");
    const tz = timezone ?? "America/New_York";
    const newEvt: Event = {
      id: `EVT-${nextEvtSeq++}`,
      subject,
      organizer: { emailAddress: { name: org.displayName, address: org.mail } },
      attendees: [
        { emailAddress: { name: org.displayName, address: org.mail }, type: "required", status: { response: "organizer" } },
        ...attendees.map((a) => ({
          emailAddress: { name: a.email.split("@")[0], address: a.email },
          type: (a.type ?? "required") as "required" | "optional",
          status: { response: "none" as const },
        })),
      ],
      start: { dateTime: start_iso, timeZone: tz },
      end:   { dateTime: end_iso,   timeZone: tz },
      location: { displayName: location ?? (is_online_meeting ? "Microsoft Teams" : "") },
      isOnlineMeeting: is_online_meeting ?? true,
      categories: [],
      showAs: "busy",
      mailbox: org.id,
      bodyPreview: body_preview ?? "",
    };
    events.push(newEvt);
    return text({ event: newEvt, receipt: `Booked: ${newEvt.id} · ${newEvt.subject} · ${newEvt.start.dateTime} ${newEvt.start.timeZone}` });
  }
);

// ── Files (OneDrive / SharePoint) ─────────────────────────────────────────

server.registerTool(
  "m365_search_files",
  {
    title: "Search OneDrive + SharePoint files",
    description:
      "Search files by name, content summary, site, or path substring. " +
      "Returns lightweight summaries; use m365_get_file for full metadata.",
    inputSchema: {
      query: z.string().min(1).describe("Substring matched against name + contentSummary + path."),
      site: z.string().optional().describe("Filter to one site (e.g. 'Finance')."),
      drive: z.enum(["onedrive", "sharepoint"]).optional(),
      shared_with: z.string().optional().describe("Show only files shared with this EMP-* id."),
      limit: z.number().int().min(1).max(50).optional(),
    },
  },
  async ({ query, site, drive, shared_with, limit }) => {
    const q = query.toLowerCase();
    let pool = files.filter(
      (f) =>
        f.name.toLowerCase().includes(q) ||
        f.contentSummary.toLowerCase().includes(q) ||
        f.path.toLowerCase().includes(q)
    );
    if (site) pool = pool.filter((f) => f.site.toLowerCase().includes(site.toLowerCase()));
    if (drive) pool = pool.filter((f) => f.drive === drive);
    if (shared_with) pool = pool.filter((f) => f.sharedWith.some((g) => g.user.id === shared_with));
    pool = [...pool].sort((a, b) => b.lastModifiedDateTime.localeCompare(a.lastModifiedDateTime));
    return text({ files: pool.slice(0, limit ?? 20).map(summariseFile), total: pool.length });
  }
);

server.registerTool(
  "m365_get_file",
  {
    title: "Get one file (full metadata)",
    description: "Fetch a single file by id including the full sharedWith list and content summary.",
    inputSchema: { file_id: z.string().describe("File id, e.g. FILE-50001.") },
  },
  async ({ file_id }) => {
    const f = files.find((x) => x.id === file_id);
    return f ? text(f) : notFound("file", file_id);
  }
);

// ── Teams chats ──────────────────────────────────────────────────────────

server.registerTool(
  "m365_list_chats",
  {
    title: "List Teams chats for a user",
    description:
      "List the 1:1, group, and channel chats a user participates in, most-recent first.",
    inputSchema: {
      user: z.string().describe("EMP-* id, UPN, or mail."),
      chat_type: z.enum(["oneOnOne", "channel", "group"]).optional(),
      limit: z.number().int().min(1).max(50).optional(),
    },
  },
  async ({ user, chat_type, limit }) => {
    const u = findUser(user);
    if (!u) return notFound("user", user);
    let pool = chats.filter((c) => c.members.some((m) => m.id === u.id));
    if (chat_type) pool = pool.filter((c) => c.chatType === chat_type);
    pool = [...pool].sort((a, b) => b.lastUpdatedDateTime.localeCompare(a.lastUpdatedDateTime));
    return text({ chats: pool.slice(0, limit ?? 20).map(summariseChat), total: pool.length });
  }
);

server.registerTool(
  "m365_search_chat_messages",
  {
    title: "Search Teams chat messages",
    description:
      "Search across a user's chat messages by substring; optionally constrain to a single chat or " +
      "messages where the user is mentioned.",
    inputSchema: {
      user: z.string().describe("Mailbox / Teams user: EMP-* id, UPN, or mail."),
      query: z.string().optional().describe("Substring on message body."),
      chat_id: z.string().optional().describe("Restrict to a single chat."),
      mentioned_only: z.boolean().optional().describe("Only return messages where the user is @mentioned."),
      from_date: z.string().optional(),
      to_date: z.string().optional(),
      limit: z.number().int().min(1).max(100).optional(),
    },
  },
  async ({ user, query, chat_id, mentioned_only, from_date, to_date, limit }) => {
    const u = findUser(user);
    if (!u) return notFound("user", user);
    const pool: { chat_id: string; chat_topic: string; message: ChatMessage }[] = [];
    for (const c of chats) {
      if (chat_id && c.id !== chat_id) continue;
      if (!c.members.some((m) => m.id === u.id)) continue;
      for (const m of c.messages) {
        if (from_date && m.createdDateTime < from_date) continue;
        if (to_date && m.createdDateTime > to_date) continue;
        if (mentioned_only && !m.mentions.some((mn) => mn.mentioned.user.id === u.id)) continue;
        if (query) {
          const q = query.toLowerCase();
          if (!m.body.content.toLowerCase().includes(q)) continue;
        }
        pool.push({ chat_id: c.id, chat_topic: c.topic, message: m });
      }
    }
    pool.sort((a, b) => b.message.createdDateTime.localeCompare(a.message.createdDateTime));
    return text({ matches: pool.slice(0, limit ?? 25), total: pool.length });
  }
);

// ── Boot ──────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
