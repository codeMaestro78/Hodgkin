import { expect, it } from "vitest";
import {
  ApprovalRequestSchema,
  BatchRequestSchema,
  CreateResearchRunRequestSchema,
  ScheduleRequestSchema,
} from "../src/index.js";

it("requires approval by default for individual and automated research", () => {
  expect(
    CreateResearchRunRequestSchema.parse({ question: "Compare queues" })
      .requireApproval,
  ).toBe(true);
  expect(
    BatchRequestSchema.parse({
      questions: ["Compare queues"],
      idempotencyKey: "fixture-unique-key",
    }).requireApproval,
  ).toBe(true);
  expect(
    ScheduleRequestSchema.parse({
      question: "Compare queues",
      intervalMinutes: 60,
      idempotencyKey: "fixture-unique-key",
    }).requireApproval,
  ).toBe(true);
});

it("enforces batch and schedule bounds", () => {
  expect(
    BatchRequestSchema.safeParse({
      questions: Array(21).fill("Compare queues"),
      idempotencyKey: "fixture-unique-key",
    }).success,
  ).toBe(false);
  expect(
    ScheduleRequestSchema.safeParse({
      question: "Compare queues",
      intervalMinutes: 59,
      idempotencyKey: "fixture-unique-key",
    }).success,
  ).toBe(false);
});

it("accepts explicit research modes on new batches and schedules", () => {
  expect(
    BatchRequestSchema.parse({
      questions: ["Compare queues"],
      idempotencyKey: "fixture-unique-key",
      mode: "deep",
    }).mode,
  ).toBe("deep");
  expect(
    ScheduleRequestSchema.parse({
      question: "Compare queues",
      intervalMinutes: 60,
      idempotencyKey: "fixture-unique-key",
      mode: "balanced",
    }).mode,
  ).toBe("balanced");
  expect(
    BatchRequestSchema.safeParse({
      questions: ["Compare queues"],
      idempotencyKey: "fixture-unique-key",
      mode: "unmetered",
    }).success,
  ).toBe(false);
});

it("requires a real plan reference and refuses unexpected approval fields", () => {
  expect(
    ApprovalRequestSchema.safeParse({ planId: "forged", decision: "approve" })
      .success,
  ).toBe(false);
  expect(
    ApprovalRequestSchema.safeParse({
      planId: "11111111-1111-4111-8111-111111111111",
      decision: "approve",
      tenantId: "forged",
    }).success,
  ).toBe(false);
});
