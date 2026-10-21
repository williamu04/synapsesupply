# SOP-ASN-01: Delayed inbound delivery of wood fibre

Applies to: process_type ASN_DELAY — an inbound delivery (ASN) announces a date later than the
purchase order schedule line. Key words MUST, MUST NOT, SHOULD, SHOULD NOT, MAY as in RFC 2119.

## Investigate
1. You MUST call `get_case_details` first.
2. You MUST call `analyze_stock_position` for the case's plant and material.
3. If `first_breach_day` is null, the delay is absorbed by stock and other deliveries: you MUST call
   `close_without_action`, citing the projected minimum and the safety stock, and MUST NOT create
   any order.

## Find options
4. You MUST call `find_sourcing_options` with `quantity` = the shortfall rounded **up** to the next
   10 units, and `needed_by` = `first_breach_day`.
5. You MUST NOT invent options, quantities, dates or costs. Only option_ids returned by
   `find_sourcing_options` exist.

## Decide
6. You MUST choose an option with `arrives_in_time` = true if one exists.
7. Among those, you MUST prefer compliance PASS or NOT_APPLICABLE, then the lowest
   `incremental_cost_for_quantity`.
8. You MUST NOT choose an option with compliance BLOCK, whatever its price or speed. EUDR
   (Regulation (EU) 2023/1115) prohibits placing fibre from deforested land on the market.
9. You SHOULD NOT choose a HOLD option. You MAY choose one only if no PASS or NOT_APPLICABLE option
   arrives in time; it will then go to a human, and you MUST say why.
10. You MUST NOT place a new order with the supplier whose delivery is delayed while the carrier
    notice reports a disruption affecting that supplier.
11. When two usable options differ in incremental cost by less than 10%, you SHOULD prefer the one with
    the higher `on_time_probability` (SAP RPT-1 delivery-risk prediction) and say so.
12. The quantity MUST cover the shortfall, MUST NOT exceed the option's `max_quantity`, and SHOULD
    NOT exceed the shortfall by more than 10% — this is exception handling, not replenishment.

## Act
13. You MUST call `submit_action` exactly once, listing every other option in
    `rejected_alternatives` with a one-line reason in plain business words, at most 12 words
    (e.g. "BLOCK: deforestation alert", "arrives 3 Nov, one day after stock runs low"). Do not
    quote field names or SOP rule numbers; planners read these reasons in Joule.
14. You MUST NOT retry or submit a second action after a DENY or ESCALATE decision. The policy
    decision is final for the agent; humans take it from there.

## Report
15. Finish with a summary of at most five sentences for the planner: what happened, the decision,
    the SAP document if one was created, and what a human needs to do, if anything.
16. You MUST NOT state any number that did not come from a tool result.
