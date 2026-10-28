import { inlineMarks } from "../inline";
import { modelBlocks } from "../modelText";

/** Claude's reply as paragraphs and bullet lists, with **bold** and `code` spans. */
export function ModelText({ text, className }: { text: string; className?: string }) {
  return (
    <div className={`model-text ${className ?? ""}`}>
      {modelBlocks(text).map((b, i) => b.kind === "ul"
        ? <ul key={i}>{b.items.map((item, j) => <li key={j}>{inlineMarks(item)}</li>)}</ul>
        : <p key={i}>{b.lines.flatMap((line, j) => (j ? [<br key={j} />, ...inlineMarks(line)] : inlineMarks(line)))}</p>)}
    </div>
  );
}
