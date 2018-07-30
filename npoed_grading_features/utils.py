from functools import wraps

from django.conf import settings
from .models import NpoedGradingFeatures


def vertical_grading_enabled(course_id):
    return settings.FEATURES.get("ENABLE_GRADING_FEATURES") and NpoedGradingFeatures.is_vertical_grading_enabled(course_id)

VERTICAL_CATEGORY = 'vertical'


def find_drop_index(percents, weights):
    """
    G = sum(w[i]p[i])/sum(w[i])
    G'[j] = sum(w[i]p[i])/sum(w[i]) : i!=j
    gain[j] = G'[j] - G
    return: max(delta)
    """
    length = len(percents)
    if len(percents) == len(weights) == 1:
        return 0
    top = sum([percents[i]*weights[i] for i in range(length)])
    bot = sum(weights)
    gain = []
    for pair in zip(weights, percents):
        gain.append(pair[0] * (top - bot * pair[1]) / (bot - pair[0]))
    return gain.index(max(gain))


def patch_function(func, implementation, dynamic_key=None):
    @wraps(func)
    def wrap_static(*args, **kwargs):
        return implementation(*args, **kwargs)

    if dynamic_key is None:
        return wrap_static

    @wraps(func)
    def wrap_dynamic(*args, **kwargs):
        if dynamic_key(args, kwargs):
            return implementation(*args, **kwargs)
        else:
            return func(*args, **kwargs)
    return wrap_dynamic
