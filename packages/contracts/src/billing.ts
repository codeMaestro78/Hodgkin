import { z } from "zod";

export const BillingEntitlementSchema = z
  .object({
    status: z.enum(["not_configured", "active"]),
    planKey: z.enum(["free", "scholar", "investigator"]).nullable().optional(),
    catalogVersion: z.string().min(1).max(64).nullable().optional(),
    periodStart: z.iso.datetime({ offset: true }).nullable().optional(),
    periodEnd: z.iso.datetime({ offset: true }).nullable().optional(),
    allowanceUnits: z.number().int().nonnegative().nullable().optional(),
    consumedUnits: z.number().int().nonnegative().nullable().optional(),
    reservedUnits: z.number().int().nonnegative().nullable().optional(),
    availableUnits: z.number().int().nonnegative().nullable().optional(),
  })
  .strict()
  .superRefine((entitlement, context) => {
    const projectionFields = [
      entitlement.planKey,
      entitlement.catalogVersion,
      entitlement.periodStart,
      entitlement.periodEnd,
      entitlement.allowanceUnits,
      entitlement.consumedUnits,
      entitlement.reservedUnits,
      entitlement.availableUnits,
    ];
    if (entitlement.status === "not_configured") {
      if (projectionFields.some((value) => value != null)) {
        context.addIssue({
          code: "custom",
          message: "Unconfigured entitlements cannot contain balances",
        });
      }
      return;
    }
    if (projectionFields.some((value) => value == null)) {
      context.addIssue({
        code: "custom",
        message: "Active entitlements require a complete projection",
      });
      return;
    }
    if (
      Date.parse(entitlement.periodStart!) >=
        Date.parse(entitlement.periodEnd!) ||
      entitlement.availableUnits !==
        entitlement.allowanceUnits! -
          entitlement.consumedUnits! -
          entitlement.reservedUnits!
    ) {
      context.addIssue({
        code: "custom",
        message: "Billing period and balance fields must reconcile",
      });
    }
  });

export type BillingEntitlement = z.infer<typeof BillingEntitlementSchema>;
