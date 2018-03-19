from collections import OrderedDict
from functools import wraps

from lazy import lazy
from django.conf import settings

from xblock.fields import Integer, Scope

from .utils import get_vertical_score, vertical_grading_enabled, drop_minimal_vertical_from_subsection_grades
_ = lambda text: text


def build_subsection_grade(class_):

    def _vertical_compute_block_score(
            self,
            block_key,
            course_structure,
            submissions_scores,
            csm_scores,
            persisted_block=None,
    ):
        vertical_pseudo_problem_score = get_vertical_score(
            block_key,
            course_structure,
            submissions_scores,
            csm_scores,
            persisted_block
        )
        if vertical_pseudo_problem_score:
            self.problem_scores[block_key] = vertical_pseudo_problem_score

    def _compute_block_score(self, *args, **kwargs):
        if vertical_grading_enabled(self.location.course_key):
            return self._vertical_compute_block_score(*args, **kwargs)
        else:
            return self._problem_compute_block_score(*args, **kwargs)

    class_._problem_compute_block_score = class_._compute_block_score
    class_._vertical_compute_block_score = _vertical_compute_block_score
    class_._compute_block_score = _compute_block_score
    return class_


def build_zero_subsection_grade(class_):

    def _vertical_problem_scores(self):
        """
        Overrides the problem_scores member variable in order
        to return empty scores for all scorable problems in the
        course.
        """
        from lms.djangoapps.grades.scores import possibly_scored #placed here to avoid circular import

        locations = OrderedDict()  # dict of problem locations to ProblemScore
        for block_key in self.course_data.structure.post_order_traversal(
                filter_func=possibly_scored,
                start_node=self.location,
        ):
            vertical_score = get_vertical_score(
                block_key,
                course_structure=self.course_data.structure,
                submissions_scores={},
                csm_scores={},
                persisted_block=None,
            )
            if vertical_score:
                locations[block_key] = vertical_score
        return locations

    def problem_scores(self):
        if vertical_grading_enabled(self.location.course_key):
            return self._vertical_problem_scores
        else:
            return self._old_problem_scores

    class_._old_problem_scores= class_.problem_scores
    class_._vertical_problem_scores = lazy(_vertical_problem_scores)
    class_.problem_scores = property(problem_scores)
    return class_


def build_vertical_block(class_):
    class_.weight = Integer(
        display_name=_("Weight"),
        help=_(
            "Defines the contribution of the vertical to the category score."),
        default=0.0,
        scope=Scope.settings
    )

    def student_view(self, context):
        """
        Shows vertical weight at the lms page.
        We suppose that nobody would set vertical
        weights with enabled VerticalGrading and turn
        it off later.
        Otherwise we would have to check if GradingFeatures
        enabled every time we render block.
        """
        if getattr(self,'weight', None):
            context['weight_string'] = _("Unit weight: {}").format(self.weight)
        return self._student_view(context)
    class_._student_view = class_.student_view
    class_.student_view = student_view
    return class_


def build_create_xblock_info(func):
    """
    This is decorator for cms.djangoapps.contentstore.item.py:create_xblock_info
    It adds vertical block weight to the available for rendering info
    """

    @wraps(func)
    def wrapped(*args, **kwargs):
        xblock = kwargs.get('xblock', False) or args[0]
        xblock_info = func(*args, **kwargs)
        if not vertical_grading_enabled(xblock.location.course_key):
            return xblock_info
        if xblock_info.get("category", False) == 'vertical':
            weight = getattr(xblock, 'weight', 0)
            xblock_info['weight'] = weight
            xblock_info['vertical_grading'] = True
            parent_xblock = kwargs.get('parent_xblock', None)
            if parent_xblock:
                xblock_info['format'] = parent_xblock.format
        if xblock_info.get("category", False) == 'sequential':
            xblock_info['vertical_grading'] = True
        return xblock_info

    return wrapped


def build_assignment_format_grader(class_):
    class_.problem_grade = class_.grade

    def get_course_id_from_grade_sheet(grade_sheet):
        for category_dict in grade_sheet.values():
            for key in category_dict:
                return key.course_key
        return None

    def grade(self, grade_sheet, generate_random_scores=False):
        course_key = get_course_id_from_grade_sheet(grade_sheet)
        if not vertical_grading_enabled(course_key):
            return self.problem_grade(grade_sheet, generate_random_scores)
        drop_count = self.drop_count
        self.drop_count = 0
        subsection_grades = grade_sheet.get(self.type, {})
        for n in range(drop_count):
            subsection_grades = drop_minimal_vertical_from_subsection_grades(subsection_grades)
        grade_sheet[self.type] = subsection_grades

        result = self.problem_grade(grade_sheet, generate_random_scores)
        self.drop_count = drop_count
        return result

    class_.grade = grade
    return class_


replaced = {
    "SubsectionGrade": build_subsection_grade,
    "ZeroSubsectionGrade": build_zero_subsection_grade,
    "AssignmentFormatGrader": build_assignment_format_grader,
    "VerticalBlock": build_vertical_block,
    "create_xblock_info": build_create_xblock_info
}


def enable_vertical_grading(obj):
    if not settings.FEATURES.get("ENABLE_GRADING_FEATURES", False):
        return obj
    name = obj.__name__
    if name in replaced:
        constructor = replaced.get(name)
        return constructor(obj)
    return obj
