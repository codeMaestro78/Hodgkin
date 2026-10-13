"use client";

// shadcn Tabs composition, adapted to this project's semantic CSS system.
// Radix owns keyboard navigation, focus management and panel relationships.
import * as TabsPrimitive from "@radix-ui/react-tabs";

export const Tabs = TabsPrimitive.Root;
export const TabsList = TabsPrimitive.List;
export const TabsTrigger = TabsPrimitive.Trigger;
export const TabsContent = TabsPrimitive.Content;
