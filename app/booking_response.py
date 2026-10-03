"""Booking replies/actions decided by trusted call state, before an LLM call."""


def trusted_booking_response(state, *, after_tool=False, allow_actions=True):
    if state.mutation_uncertain:
        return {"content": state.guard_reply("", state.results)}
    if after_tool:
        # Existing guards preserve errors, price truth and actual write state.
        choose_room = bool(state.results and state.results[-1].get("needs_room_type"))
        if state.pending or state.turn_mutation or choose_room:
            return {"content": state.guard_reply("", state.results)}
        return None
    if not allow_actions:
        return None
    pending = state.pending
    approval = state.cancel_approval
    if pending and pending.get("approved"):
        return {
            "name": "confirm_booking" if pending.get("kind") == "stay" else "confirm_slot_booking",
            "arguments": {"hold_id": pending["hold_id"]},
        }
    if approval and approval["booking_id"] in state.bookings:
        booking_id = approval["booking_id"]
        return {
            "name": "cancel_booking" if state.booking_kinds.get(booking_id) == "stay" else "cancel_slot_booking",
            "arguments": {"booking_id": booking_id},
        }
    return None
