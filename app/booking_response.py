"""Booking replies/actions decided by trusted call state, before an LLM call."""


def trusted_booking_response(state, *, after_tool=False, allow_actions=True):
    if state.mutation_uncertain:
        return {"content": state.guard_reply("", state.results)}
    if after_tool:
        # Existing guards preserve errors, price truth and actual write state.
        choose_room = bool(state.results and state.results[-1].get("needs_room_type"))
        if state.pending or state.turn_mutation or choose_room:
            return {"content": state.guard_reply("", state.results)}
        faq = state.faq_response(allow_actions=allow_actions)
        if faq:
            return faq
        if state.spa_hours_inquiry and state.results:
            return {"content": state.guard_reply("", state.results)}
        if state.business == "restaurant" and state.results:
            result = state.results[-1]
            if (
                result.get("error")
                or result.get("kind") == "table"
                or isinstance(result.get("tables"), list)
            ):
                return {"content": state.guard_reply("", state.results)}
        return None
    faq = state.faq_response(allow_actions=allow_actions)
    if faq:
        return faq
    if not allow_actions:
        return None
    pending = state.pending
    approval = state.cancel_approval
    if pending and pending.get("approved"):
        return {
            "name": {"stay": "confirm_booking", "table": "confirm_table_booking"}.get(
                pending.get("kind"), "confirm_slot_booking"
            ),
            "arguments": {"hold_id": pending["hold_id"]},
        }
    if approval and approval["booking_id"] in state.bookings:
        booking_id = approval["booking_id"]
        return {
            "name": {"stay": "cancel_booking", "table": "cancel_table_booking"}.get(
                state.booking_kinds.get(booking_id), "cancel_slot_booking"
            ),
            "arguments": {"booking_id": booking_id},
        }
    inquiry = state.inquiry_reply()
    if inquiry:
        return {"content": inquiry}
    if state.spa_hours_inquiry and not state.results:
        return {"name": "get_slot_catalogue", "arguments": {}}
    return None
