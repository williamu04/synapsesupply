// Model and backend text as the console shows it: no emoji status marks, no em dashes. Claude's summaries
// and the stored recordings use both; the console's style is words and commas. Line breaks are kept.

const MARKS = /[✅✔✓✗✘❌❎⚠⛔⭐★\u{1F6AB}\u{1F534}\u{1F7E2}]️?/gu;

export function plainText(text: string): string {
  return text
    .replace(MARKS, "")
    .replace(/[ \t]*—[ \t]*/g, ", ")
    .replace(/,[ \t]*([,.;:])/g, "$1")
    .replace(/[ \t]+([,.;:])/g, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/^[ \t]*,[ \t]*/gm, "")
    .trim();
}
