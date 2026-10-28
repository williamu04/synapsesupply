import type { ReactNode } from "react";
import { plainText } from "./plainText";

/** Model text with `**bold**` spans as React nodes (Claude writes markdown bold; Joule renders it).
 *  An unmatched `**` stays as plain text. Em dashes and emoji marks are cleaned first (plainText). */
export function inlineBold(text: string): ReactNode[] {
  const parts = plainText(text).split("**");
  const out: ReactNode[] = [];
  parts.forEach((part, i) => {
    // Odd parts sit between two markers, except the last one when the final `**` has no partner.
    if (i % 2 === 0) out.push(part);
    else if (i < parts.length - 1) out.push(<strong key={i}>{part}</strong>);
    else out.push(`**${part}`);
  });
  return out.filter((n) => n !== "");
}
