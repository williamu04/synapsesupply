# SOP-REQ-01: Buyer request through SAP Joule

Applies to: process_type USER_REQUEST — a person asks, in natural language, for a sourcing action
or a supply question. Key words MUST, MUST NOT, SHOULD, SHOULD NOT, MAY as in RFC 2119.

## Understand
1. You MUST call `get_case_details` first and read both the request text and its triage.
2. If the request names a supplier, you MUST call `check_supplier_compliance` for that supplier
   with the requested quantity before anything else.

## Purchase requests
3. You MUST call `analyze_stock_position` for the plant and material, then `find_sourcing_options`
   with the requested quantity and `needed_by` = `first_breach_day` if there is one, otherwise
   today + 7 days.
4. You MUST submit exactly what the buyer asked for — the requested supplier's option and the
   requested quantity — through `submit_action`, even if the compliance gate failed. The buyer is
   entitled to an auditable policy decision; you MUST NOT silently substitute another supplier.
5. If the requested supplier has no option (no purchasing info record), you MUST NOT submit
   anything; explain this and recommend the best compliant option instead.
6. If the decision is DENY or ESCALATE, you MUST explain the reason in plain language and SHOULD
   recommend the best compliant alternative from `find_sourcing_options`, naming its supplier or
   plant, arrival date and incremental cost. You MUST NOT submit a second action: the buyer decides.

## Questions
7. If the request is a question, not a purchase, you MUST answer it from tool results only and then
   call `close_without_action`. When you mention the reorder point, compare it with
   `inventory_position` (on hand + open inbound), never with on-hand stock alone.

## Report
8. Reply to the buyer in at most five plain sentences. You MUST NOT state any number that did not
   come from a tool result.
9. Name alternatives by supplier or plant (e.g. "a transfer from Mill Jambi-2"). You MUST NOT ask the
   buyer to quote option_ids or to "resubmit" anything: they can simply ask for the alternative in
   their own words.
