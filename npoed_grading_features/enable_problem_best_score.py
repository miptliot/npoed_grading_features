from django.conf import settings

from .models import NpoedGradingFeatures
from .utils import patch_function


def set_score(user_id, usage_key, score, max_score):
    """
    Set the score and max_score for the specified user and xblock usage
    if score is rising or grade is new
    """
    from courseware.models import StudentModule
    student_module, created = StudentModule.objects.get_or_create(
        student_id=user_id,
        module_state_key=usage_key,
        course_id=usage_key.course_key,
        defaults={
            'grade': score,
            'max_grade': max_score,
        }
    )
    if not created:
        should_update = (student_module.max_grade != max_score) or (student_module.grade < score)
        if should_update:
            student_module.grade = score
            student_module.max_grade = max_score
            student_module.save()
    return student_module.modified


def build_set_score(func):
    is_enabled_for_course = lambda args, kwargs: NpoedGradingFeatures.is_problem_best_score_enabled(args[1].course_key)
    return patch_function(func, set_score, dynamic_key=is_enabled_for_course)


replaced = {
    "set_score": build_set_score,
}


def enable_problem_best_score(func):
    if not settings.FEATURES.get("ENABLE_GRADING_FEATURES", False):
        return func
    name = func.__name__
    if name in replaced:
        constructor = replaced.get(name)
        return constructor(func)
    return func
