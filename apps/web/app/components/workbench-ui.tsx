"use client";

import type { ComponentProps, ReactNode } from "react";
import clsx from "clsx";
import { Dialog } from "@base-ui/react/dialog";
import { ToggleGroup as BaseToggleGroup } from "@base-ui/react/toggle-group";
import { Toggle } from "@base-ui/react/toggle";

export function Button({
  className,
  variant = "primary",
  ...props
}: ComponentProps<"button"> & { variant?: "primary" | "outline" | "quiet" }) {
  return (
    <button
      className={clsx("desk-button", `desk-button-${variant}`, className)}
      {...props}
    />
  );
}
export function FieldGroup({ children }: { children: ReactNode }) {
  return <div className="desk-field-group">{children}</div>;
}
export function Field({
  children,
  invalid = false,
}: {
  children: ReactNode;
  invalid?: boolean;
}) {
  return (
    <div className="desk-field" data-invalid={invalid || undefined}>
      {children}
    </div>
  );
}
export function FieldLabel(props: ComponentProps<"label">) {
  return <label className="desk-field-label" {...props} />;
}
export function Alert({ children }: { children: ReactNode }) {
  return (
    <div className="desk-alert" role="alert">
      {children}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="desk-empty">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={clsx("desk-skeleton", className)} aria-hidden="true" />
  );
}
export function Badge({ children }: { children: ReactNode }) {
  return <span className="desk-badge">{children}</span>;
}
export function ToggleGroup({
  value,
  onChange,
  label,
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  children: ReactNode;
}) {
  return (
    <BaseToggleGroup
      className="desk-toggle-group"
      value={[value]}
      onValueChange={(values) => {
        if (values[0]) onChange(values[0]);
      }}
      aria-label={label}
    >
      {children}
    </BaseToggleGroup>
  );
}
export function ToggleGroupItem({
  children,
  value,
}: {
  children: ReactNode;
  value: string;
}) {
  return (
    <Toggle className="desk-toggle-item" value={value}>
      {children}
    </Toggle>
  );
}

/** Named composition follows shadcn Sheet, backed by Base UI focus/dismissal. */
export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;
export const SheetClose = Dialog.Close;
export const SheetTitle = Dialog.Title;
export function SheetContent({ children }: { children: ReactNode }) {
  return (
    <Dialog.Portal>
      <Dialog.Backdrop className="desk-sheet-backdrop" />
      <Dialog.Popup className="desk-sheet-popup">{children}</Dialog.Popup>
    </Dialog.Portal>
  );
}
