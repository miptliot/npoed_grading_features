from collections import OrderedDict
from functools import wraps

from django.conf import settings

from xblock.fields import Integer, Scope, Boolean

from .utils import find_drop_index, vertical_grading_enabled
_ = lambda text: text


def uniqueify(iterable):
    """Looks weird, but that is how it is done in lms.djangoapps.grades"""
    return OrderedDict([(item, None) for item in iterable]).keys()


def build_course_grade(cls):
    class CourseVerticalGradeBase(cls):
        def _get_subsection_grades(self, course_structure, chapter_key):
            """
            Returns a list of subsection or vertical grades for the given chapter.
            Checks course field to decide which grading model to apply
            """
            vertical_mode = getattr(self.course_data.course, "vertical_grading", False)
            grades = []
            for subsection_key in uniqueify(course_structure.get_children(chapter_key)):
                if not vertical_mode:
                    grades.append(self._get_subsection_grade(course_structure[subsection_key]))
                else:
                    subsection = course_structure[subsection_key]
                    vertical_keys = course_structure.get_children(subsection_key)
                    for vkey in vertical_keys:
                        vertical = course_structure[vkey]
                        grade = self._get_subsection_grade(vertical)
                        grade.format = subsection.format
                        grade.weight = vertical.weight
                        grades.append(grade)
            return grades
    return CourseVerticalGradeBase


def build_course_fields(cls):
    default = getattr(settings, "VERTICAL_GRADING_DEFAULT", False)
    # TODO: Later it can be replaced by waffle flags

    class NpoedCourseFields(cls):
        vertical_grading = Boolean(
            display_name=_("Vertical Grading"),
            help=_("This field is not intended to be changed from AdvancedSettings"),
            default=default,
            scope=Scope.settings
        )
    return NpoedCourseFields


def build_vertical_block(cls):

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
    cls._student_view = cls.student_view
    cls.student_view = student_view
    cls.weight = Integer(
            display_name=_("Weight"),
            help=_(
                "Defines the contribution of the vertical to the category score."),
            default=0.0,
            scope=Scope.settings
        )

    return cls


def build_create_xblock_info(func):
    """
    This is decorator for cms.djangoapps.contentstore.item.py:create_xblock_info
    It makes vertical block weight available for rendering info
    """
    @wraps(func)
    def wrapped(*args, **kwargs):
        xblock = kwargs.get('xblock', False) or args[0]
        xblock_info = func(*args, **kwargs)
        if not vertical_grading_enabled(xblock.location.course_key):
            return xblock_info
        if xblock_info.get("category", "") == 'vertical':
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


def build_course_metadata(cls):
    new_filtered_list = cls.FILTERED_LIST
    new_filtered_list.append("vertical_grading")

    class NpoedCourseMetadata(cls):
        """
        Hides vertical_grading attr from Advanced Settings at cms
        """
        FILTERED_LIST = new_filtered_list

    return cls


def build_assignment_format_grader(cls):

    class FlexibleNpoedGrader(cls):
        """
        Flexible grader to apply vertical or sequential grading.
        Decision is based on weight attr existence, which can only
        be added at CourseVerticalGradeBase
        """

        def grade(self, grade_sheet, generate_random_scores=False):
            scores = grade_sheet.get(self.type, {}).values()
            vertical_mode = all([hasattr(x,'weight') for x in scores])
            if not vertical_mode:
                return super(FlexibleNpoedGrader, self).grade(grade_sheet, generate_random_scores)

            drop_count = self.drop_count
            self.drop_count = 0
            result = super(FlexibleNpoedGrader, self).grade(grade_sheet, generate_random_scores)
            if not scores:
                return result
            self.drop_count = drop_count

            breakdown = result['section_breakdown']

            if len(breakdown) == 1:
                # In this case AssignmentGrader returns only total score, we don't have grades per item
                if self.drop_count == 0:
                    return result
                else:
                    # AssignmentGrader didn't drop grade because we have turned off drop_count, we should do it manually
                    breakdown[0]['percent'] = 0
                    breakdown[0]['detail'] = u"{section_type} = {percent:.0%}".format(
                       percent=0,
                       section_type=self.type,
                    )
                    return {
                        'section_breakdown': breakdown,
                        'percent':0
                    }

            percent = [x['percent'] for x in breakdown if 'prominent' not in x]
            weights = [x.weight for x in scores]
            for k in range(self.drop_count):
                index = find_drop_index(percent, weights)
                percent.pop(index)
                weights.pop(index)
                breakdown.pop(index)
            total_weight = sum(weights)
            if total_weight:
                total_percent = sum([weights[i]*percent[i] for i in range(len(weights))])/total_weight
            else:
                total_percent = 0
            grading = {
                "section_breakdown": breakdown,
                "percent": total_percent
            }
            return grading

    return FlexibleNpoedGrader

replaced = {
    "CourseGradeBase": build_course_grade,
    "CourseFields": build_course_fields,
    "AssignmentFormatGrader": build_assignment_format_grader,
    "VerticalBlock": build_vertical_block,
    "CourseMetadata": build_course_metadata,
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
