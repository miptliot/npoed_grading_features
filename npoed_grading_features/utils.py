from functools import wraps

from django.conf import settings
from .models import NpoedGradingFeatures


def vertical_grading_enabled(course_id):
    return settings.FEATURES.get("ENABLE_GRADING_FEATURES") and NpoedGradingFeatures.is_vertical_grading_enabled(course_id)

VERTICAL_CATEGORY = 'vertical'


def get_vertical_score(
        block_key,
        course_structure,
        submissions_scores,
        csm_scores,
        persisted_block=None
):
    """
    In vertical grading we the basic scoring element is Unit(vertical) instead of problem.
    To implement this we emulate vertical scoring by single ProblemScore:
    if grading is called for vertical, we take all it's descendant problems, and set
    unit.raw_earned = sum(problem.raw_earned),  unit.raw_possible = sum(problem.raw_possible).
    Resulted fake ProblemScore that represent unit scores are graded as usually to calculate
    subsection grades.
    """
    from lms.djangoapps.grades.scores import get_score, ProblemScore # placed here to avoid circular import

    if block_key.category != VERTICAL_CATEGORY:
        return
    vertical_weight = getattr(course_structure[block_key], "weight", None)
    if not vertical_weight:
        return
    children_keys = course_structure.get_children(block_key)
    children_scores = []
    for child_key in children_keys:
        try:
            block = course_structure[child_key]
        except KeyError:
            # It's possible that the user's access to that
            # block has changed since the subsection grade
            # was last persisted.
            pass
        else:
            if getattr(block, 'has_score', False):
                problem_score = get_score(
                    submissions_scores,
                    csm_scores,
                    persisted_block,
                    block,
                )
                if problem_score:
                    children_scores.append(problem_score)
    if not children_scores:
        return
    vertical_possible = sum(score.possible for score in children_scores)
    vertical_earned = sum(score.earned for score in children_scores)
    weighted_earned = vertical_weight * float(vertical_earned) / vertical_possible
    weighted_possible = vertical_weight
    inner_first_attempted = list(score.first_attempted for score in children_scores)
    vertical_attempted = max(inner_first_attempted) if inner_first_attempted else None
    vertical_graded = any(score.graded for score in children_scores) and bool(weighted_possible)
    vertical_pseudo_problem = ProblemScore(
        raw_earned=weighted_earned,
        raw_possible=weighted_possible,
        weighted_earned=weighted_earned,
        weighted_possible=weighted_possible,
        weight=1,
        graded=vertical_graded,
        first_attempted=vertical_attempted
    )
    return vertical_pseudo_problem


def drop_minimal_vertical_from_subsection_grades(subsection_grades):
    """
    This function finds the worst block and drops it from the subsection grades.
    The definition of the worst block itself is moved into _find_worst_score
    which takes not a SubsectionGrades but pairs to ease testing.
    """
    tree = _build_tree_from_grades(subsection_grades)
    best_score_drop_index = _find_worst_score(tree)
    if best_score_drop_index is None:
        return subsection_grades
    modified_grade = subsection_grades[best_score_drop_index[0]]
    subtracted_score = modified_grade.problem_scores.pop(best_score_drop_index[1])
    modified_grade.graded_total.earned -= subtracted_score.earned
    modified_grade.graded_total.possible -= subtracted_score.possible

    modified_grade.all_total.earned -= subtracted_score.earned
    modified_grade.all_total.possible -= subtracted_score.possible
    if not modified_grade.graded_total.possible:
        subsection_grades.pop(best_score_drop_index[0])
    return subsection_grades


def _find_worst_score(subsection_grades_tree):
    """
    Takes structure  of category grading tree in
    vertical grading case:
    {
        SubsectionKey1: {BlockKey1:(earned, possible), BlockKey2: ...},
        SubsectionKey2: {...}
    }
    returns:
        N, BlockKey - subsection number, unit's block key
        None - if no need to drop anything(no grading elements)

    """
    best_score_drop_index = None
    subsection_scores = {}
    for subsection_key, subsection_unit_grades in subsection_grades_tree.iteritems():
        earned, possible = zip(*subsection_unit_grades.values())
        subsection_scores[subsection_key] = (sum(earned), sum(possible))

    def grade_without(subsection_key, unit_key):
        removed_grade = subsection_grades_tree[subsection_key][unit_key]
        changed_score = subsection_scores[subsection_key]
        modified_subsection_score = (
            changed_score[0] - removed_grade[0],
            changed_score[1] - removed_grade[1]
        )
        if modified_subsection_score[1]: # there are at least two units in subsection
            rest_percents = [
                (x[0] / x[1]) if (key != subsection_key)
                else (modified_subsection_score[0]/modified_subsection_score[1])
                for key, x in subsection_scores.iteritems()
            ]
        else: # this is the last unit
            rest_percents = [
                (x[0] / x[1])
                for key, x in subsection_scores.iteritems()
                if (key != subsection_key)
            ]

        if not rest_percents:
            # this is the only possible drop, give him the highest rank
            return 1.
        else:
            return sum(rest_percents)/len(rest_percents)

    best_score = sum([x[0] for x in subsection_scores.values()]) / sum([x[1] for x in subsection_scores.values()])

    for subsection_key, subsection_unit_grades in subsection_grades_tree.iteritems():
        for unit_key in subsection_unit_grades:
            score = grade_without(subsection_key, unit_key)
            if score >= best_score:
                best_score = score
                best_score_drop_index = (subsection_key, unit_key)
    return best_score_drop_index


def _build_tree_from_grades(subsection_grades):
    """
    Parses subsection grades
    :param subsection_grades:
        {
            SubsectionKey1: SubsectionGrade(),
            SubsectionKey2: SubsectionGrade()...
        }
    :return:
        {
            SubsectionKey1: {UnitKey1: tuple(earned, possible), UnitKey2:...},
            ...
        }
    """
    tree = {}
    for key, grade in subsection_grades.iteritems():
        subtree = {}
        for block_key, problem_score in grade.problem_scores.items():
            subtree[block_key] = (problem_score.earned, problem_score.possible)
        tree[key] = subtree
    return tree


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
