"""Select one business policy for HTTP and native telephone conversations."""

from .restaurant_call import RestaurantCallTools
from .telephone import CallTools


def make_call_tools(dispatcher, **kwargs) -> CallTools:
    if getattr(dispatcher, "business_type", None) == "restaurant":
        return RestaurantCallTools(dispatcher, **kwargs)
    return CallTools(dispatcher, **kwargs)
