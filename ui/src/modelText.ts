// Claude's plain-markdown replies as blocks: paragraphs (blank-line separated) and "- " bullet lists.
// Inline marks (**bold**, `code`) are left in the strings for inlineMarks. Pure and unit-tested.
import { plainText } from "./plainText";

export type Block = { kind: "p"; lines: string[] } | { kind: "ul"; items: string[] };

export function modelBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const line of plainText(text).split("\n")) {
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const last = blocks[blocks.length - 1];
    if (bullet) {
      if (last?.kind === "ul") last.items.push(bullet[1]);
      else blocks.push({ kind: "ul", items: [bullet[1]] });
    } else if (!line.trim()) {
      if (last?.kind === "p") blocks.push({ kind: "p", lines: [] });  // a blank line ends the paragraph
    } else if (last?.kind === "p") {
      last.lines.push(line.trim());
    } else {
      blocks.push({ kind: "p", lines: [line.trim()] });
    }
  }
  return blocks.filter((b) => (b.kind === "p" ? b.lines.length > 0 : true));
}
