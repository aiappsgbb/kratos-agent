#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(here, "data");

type ScheduleBlock = { date: string; start: string; end: string; status: "free" | "busy" | "tentative"; label: string; };
type Person = {
  id: string;
  name: string;
  email: string;
  role: string;
  team: string;
  location: string;
  timezone: string;
  manager_id: string | null;
  status: string;
  skills: string[];
  schedule: ScheduleBlock[];
};

const load = <T>(file: string): T => JSON.parse(readFileSync(path.join(dataDir, file), "utf-8")) as T;
const people: Person[] = load("people.json");

const withSimulationNote = <T>(obj: T) => ({ ...(obj as object), simulation_only: true });
const text = (obj: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(withSimulationNote(obj), null, 2) }] });
const notFound = (kind: string, id: string) => ({ content: [{ type: "text" as const, text: JSON.stringify({ error: "not_found", kind, id, simulation_only: true }, null, 2) }], isError: true });
const server = new McpServer({ name: "work-iq-mcp-server", version: "0.1.0" });

const normalizeName = (value: string) => value.trim().toLowerCase();
const availableSlots = (person: Person, day: string) =>
  person.schedule.filter((slot) => slot.date === day && slot.status === "free");
const resolveAvailability = (person: Person, day: string) =>
  person.schedule
    .filter((slot) => slot.date === day)
    .map((slot) => ({
      date: slot.date,
      window: `${slot.start} / ${slot.end}`,
      status: slot.status === "free" ? "Available" : slot.status === "busy" ? "Busy" : "Out of Office",
      notes: slot.label,
    }));
const commonAvailability = (matches: Person[], day: string) => {
  if (matches.length === 0) return [];
  let overlaps = availableSlots(matches[0], day).map((slot) => ({ start: slot.start, end: slot.end }));
  for (const person of matches.slice(1)) {
    overlaps = overlaps.flatMap((overlap) =>
      availableSlots(person, day)
        .map((slot) => ({
          start: new Date(overlap.start) > new Date(slot.start) ? overlap.start : slot.start,
          end: new Date(overlap.end) < new Date(slot.end) ? overlap.end : slot.end,
        }))
        .filter((slot) => new Date(slot.start) < new Date(slot.end)),
    );
  }
  return overlaps;
};
type MeetingPayload = {
  title: string;
  date: string;
  time: string;
  duration_minutes: number;
  organizer_id: string;
  attendees: string[];
  agenda: string;
};
const generateConfirmationToken = (meeting: MeetingPayload) => {
  const canonical = JSON.stringify({ ...meeting, attendees: [...meeting.attendees].sort() });
  const hash = Array.from(canonical)
    .reduce((acc, ch) => (acc * 31 + ch.charCodeAt(0)) >>> 0, 0)
    .toString(16)
    .padStart(8, "0");
  return `SIM-${hash.toUpperCase()}`;
};

server.registerTool(
  "work_iq_search_people",
  {
    title: "Search people",
    description: "Search synthetic people directory by name, title, team, location, or email. Output is simulation-only fixture data.",
    inputSchema: {
      query: z.string().describe("Search by name, role, team, location, or email."),
      limit: z.number().int().positive().optional().describe("Maximum number of matches."),
    },
  },
  async ({ query, limit }) => {
    const needle = normalizeName(query);
    let pool = people.filter((person) =>
      [person.name, person.role, person.team, person.location, person.email, ...person.skills].join(" ").toLowerCase().includes(needle),
    );
    if (limit) pool = pool.slice(0, limit);
    return text({ people: pool.map((person) => ({ ...person, title: person.role, availability: resolveAvailability(person, "2026-09-16") })), total: pool.length });
  },
);

server.registerTool(
  "work_iq_get_person",
  {
    title: "Get a person",
    description: "Return details for one synthetic person plus their current availability pattern.",
    inputSchema: {
      person_id: z.string().optional().describe("Person id."),
      email: z.string().optional().describe("Work email address."),
    },
  },
  async ({ person_id, email }) => {
    const person = people.find((entry) => (person_id && entry.id === person_id) || (email && entry.email.toLowerCase() === email.toLowerCase()));
    if (!person) return notFound("person", person_id ?? email ?? "unknown");
    return text({
      ...person,
      title: person.role,
      manager: person.manager_id,
      availability: person.schedule.map((slot) => ({
        date: slot.date,
        window: `${slot.start} / ${slot.end}`,
        status: slot.status === "free" ? "Available" : slot.status === "busy" ? "Busy" : "Out of Office",
        notes: slot.label,
      })),
    });
  },
);

server.registerTool(
  "work_iq_find_availability",
  {
    title: "Find available times",
    description: "Return the current synthetic availability for one or more people on a date. Output is simulation-only.",
    inputSchema: {
      person_ids: z.array(z.string()).min(1).describe("One or more person ids."),
      date: z.string().describe("Target date in YYYY-MM-DD format."),
    },
  },
  async ({ person_ids, date }) => {
    const peopleMatches = person_ids.map((personId) => people.find((entry) => entry.id === personId));
    const matches = peopleMatches.map((person, index) => {
      const personId = person_ids[index];
      if (!person) return { person_id: personId, error: "not_found", simulation_only: true };
      return { person: person.name, person_id: personId, date, slots: resolveAvailability(person, date) };
    });
    return text({
      date,
      matches,
      common_available_slots: peopleMatches.every((person): person is Person => Boolean(person))
        ? commonAvailability(peopleMatches, date)
        : [],
    });
  },
);

server.registerTool(
  "work_iq_prepare_meeting",
  {
    title: "Prepare a synthetic meeting",
    description: "Prepare a meeting proposal and return a deterministic confirmation token that must be supplied to create the meeting. This is simulation-only and never sends messages.",
    inputSchema: {
      title: z.string().describe("Meeting title."),
      date: z.string().describe("Meeting date in YYYY-MM-DD format."),
      time: z.string().describe("Meeting time in HH:MM local time."),
      duration_minutes: z.number().int().positive().max(480).describe("Meeting duration in minutes."),
      attendees: z.array(z.string()).min(1).describe("Attendee person ids."),
      organizer_id: z.string().describe("Organizer person id."),
      agenda: z.string().optional().describe("Meeting agenda."),
    },
  },
  async ({ title, date, time, duration_minutes, attendees, organizer_id, agenda }) => {
    const organizer = people.find((entry) => entry.id === organizer_id);
    if (!organizer) return notFound("person", organizer_id);
    const unknownAttendee = attendees.find((id) => !people.some((person) => person.id === id));
    if (unknownAttendee) return notFound("person", unknownAttendee);
    const meeting: MeetingPayload = {
      title,
      date,
      time,
      duration_minutes,
      organizer_id,
      attendees,
      agenda: agenda ?? "Review priorities and decision points.",
    };
    const token = generateConfirmationToken(meeting);
    return text({
      meeting_preview: { ...meeting, organizer_name: organizer.name },
      confirmation_token: token,
      confirmation_required: true,
      instruction: "This is a simulation only. Use the confirmation_token when calling work_iq_create_meeting.",
    });
  },
);

server.registerTool(
  "work_iq_create_meeting",
  {
    title: "Create a synthetic meeting",
    description: "Create a simulated meeting only with an explicit confirmation token from prepare_meeting. No live Microsoft 365 message is sent.",
    inputSchema: {
      title: z.string().describe("Meeting title."),
      date: z.string().describe("Meeting date in YYYY-MM-DD format."),
      time: z.string().describe("Meeting time in HH:MM local time."),
      duration_minutes: z.number().int().positive().max(480).describe("Meeting duration in minutes."),
      organizer_id: z.string().describe("Organizer person id."),
      attendees: z.array(z.string()).min(1).describe("Attendee person ids."),
      agenda: z.string().describe("Exact agenda returned in the prepared meeting."),
      confirmation_token: z.string().describe("Exact confirmation token returned by work_iq_prepare_meeting."),
      confirm: z.boolean().describe("Must be true to create the simulated meeting."),
    },
  },
  async ({ title, date, time, duration_minutes, organizer_id, attendees, agenda, confirmation_token, confirm }) => {
    const organizer = people.find((entry) => entry.id === organizer_id);
    if (!organizer) return notFound("person", organizer_id);
    const unknownAttendee = attendees.find((id) => !people.some((person) => person.id === id));
    if (unknownAttendee) return notFound("person", unknownAttendee);
    const meeting: MeetingPayload = { title, date, time, duration_minutes, organizer_id, attendees, agenda };
    const expectedToken = generateConfirmationToken(meeting);
    if (!confirm || confirmation_token !== expectedToken) {
      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            error: "confirmation_required",
            message: "Meeting creation requires a valid confirmation token from work_iq_prepare_meeting and confirm=true.",
            simulation_only: true,
          }, null, 2),
        }],
        isError: true,
      };
    }
    return text({
      meeting: {
        id: `SIM-MTG-${date.replace(/-/g, "")}-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 18)}`,
        title,
        date,
        time,
        duration_minutes,
        organizer_id,
        organizer_name: organizer.name,
        attendees,
        agenda,
        status: "scheduled",
      },
      creation_status: "simulated_only",
      instruction: "This is a simulation only. No M365 message or calendar invite was sent.",
    });
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
