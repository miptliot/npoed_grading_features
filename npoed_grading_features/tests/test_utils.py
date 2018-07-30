from collections import namedtuple
from openedx.core.djangolib.testing.utils import get_mock_request
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.partitions.partitions import (
    UserPartition, MINIMUM_STATIC_PARTITION_ID
)

from lms.djangoapps.grades.tests.utils import answer_problem
from ..models import NpoedGradingFeatures
from ..utils import find_drop_index


TestGrade = namedtuple('TestGrade', ["earn", "max", "weight"])


class ContentGroupsMixin(object):
    """
    Methods are taken from cms/lib/xblock/test_authoring_mixin.py: AuthoringMixinTestCase
    It is not mixin actually because contains test, so methods are just copied
    """
    def create_content_groups(self, content_groups):
        """
        Create a cohorted user partition with the specified content groups.
        """
        # pylint: disable=attribute-defined-outside-init
        CONTENT_GROUPS_TITLE = "Content Groups"
        self.content_partition = UserPartition(
            MINIMUM_STATIC_PARTITION_ID,
            CONTENT_GROUPS_TITLE,
            'Contains Groups for Cohorted Courseware',
            content_groups,
            scheme_id='cohort'
        )
        self.course.user_partitions = [self.content_partition]
        self.store.update_item(self.course, 0)

    def set_staff_only(self, item_location):
        """Make an item visible to staff only."""
        item = self.store.get_item(item_location)
        item.visible_to_staff_only = True
        self.store.update_item(item, 0)

    def set_group_access(self, item_location, group_ids, partition_id=None):
        """
        Set group_access for the specified item to the specified group
        ids within the content partition.
        """
        item = self.store.get_item(item_location)
        item.group_access[self.content_partition.id if partition_id is None else partition_id] = group_ids
        self.store.update_item(item, 0)


class BuildCourseMixin(object):
    """
    Mixin with methods to build, validate and grade course
    represented by tree
    """

    def _build_from_tree(self, tree):
        """
        Builds course from tree. Tree is stored in dict in a view like this:
        {
            "SectionName1":{
                "SubsectionName11_or_smth_else":("assignment_category" if graded, {
                    "BlockName111":(weight or None(means 'html'), {
                        "ProblemOrHtmlName":(earn, max)
                    }
                })
            }
        }
        """
        course = self.course
        request = self.request
        self.course_tree = {}
        to_answer = []
        for section_name, section_tree in tree.iteritems():
            current_section = ItemFactory.create(parent=course, category="chapter", display_name=section_name)
            self.course_tree[section_name] = current_section
            for subsection_name, subsection_pair in section_tree.iteritems():
                assignment_category, subsection_tree = subsection_pair
                current_subsection = ItemFactory.create(
                    parent=current_section,
                    category="sequential",
                    display_name=subsection_name,
                    graded=assignment_category is not None,
                    format=assignment_category or ""
                )
                self.course_tree[subsection_name] = current_subsection
                for unit_name, unit_pair in subsection_tree.iteritems():
                    weight, unit_tree = unit_pair
                    metadata = {} if (weight is None) else {"weight": weight}
                    current_unit = ItemFactory.create(parent=current_subsection, category="vertical",
                                                      display_name=unit_name, metadata=metadata)
                    self.course_tree[unit_name] = current_unit
                    for problem_name, problem_pair in unit_tree.iteritems():
                        earned, max_ = problem_pair

                        kwargs = {
                            "parent": current_unit,
                            "display_name": problem_name,
                            "category": "html" if max_ is None else "problem"
                        }
                        if assignment_category and not (max is None):
                            kwargs["format"] = assignment_category
                        current_problem = ItemFactory.create(**kwargs)
                        if not (max_ is None):
                            to_answer.append((current_problem, (earned, max_)))
                        self.course_tree[problem_name] = current_problem
        # Somehow 'answer_problem' must be after course building, otherwise
        # items not created
        for problem, pair in to_answer:
            earned, max_ = pair
            answer_problem(course, request, problem, score=earned, max_value=max_)

    def _check_tree(self, tree, course=None):
        if course is None:
            course = self.course
        message = "Check tree failed: {} '{}' not found. Have names: {}"
        for section_name, section_tree in tree.iteritems():
            sections = course.get_children()
            current_section = [x for x in sections if x.display_name == section_name]
            if not len(current_section):
                raise ValueError(message.format('section', section_name), [x.display_name for x in sections])
            current_section = current_section[0]
            for subsection_name, subsection_pair in section_tree.iteritems():
                assignment_category, subsection_tree = subsection_pair
                subsections = current_section.get_children()
                current_subsection = [x for x in subsections if x.display_name == subsection_name]
                if not len(current_subsection):
                    raise ValueError(message.format('subsection', subsection_name),
                                     [x.display_name for x in subsections])
                current_subsection = current_subsection[0]
                for unit_name, unit_pair in subsection_tree.iteritems():
                    weight, unit_tree = unit_pair
                    units = current_subsection.get_children()
                    current_unit = [x for x in units if x.display_name == unit_name]
                    if not len(current_unit):
                        raise ValueError(message.format('unit', unit_name, [x.display_name for x in units]))
                    current_unit = current_unit[0]
                    for problem_name, problem_pair in unit_tree.iteritems():
                        problems = current_unit.get_children()
                        current_problem = [x for x in problems if x.display_name == problem_name]
                        if not len(current_problem):
                            raise ValueError(
                                message.format('problem', problem_name, [x.display_name for x in problems]))

    def _update_grading_policy(self, grading_policy=None):
        if grading_policy is None:
            grading_policy = {
                "GRADER": [
                    {
                        "type": "Homework",
                        "min_count": 1,
                        "drop_count": 0,
                        "short_label": "HW",
                        "weight": 1.0,
                    },
                ],
                "GRADE_CUTOFFS": {
                    "Pass": 0.5,
                },
            }

        self.course.set_grading_policy(grading_policy)
        self.store.update_item(self.course, 0)
        self.course = self.store.get_course(self.course.id)

    def _grade_tree(self, tree, enable_vertical):
        self.course = self.store.get_course(self.course.id)

        def get_unit_problem_pairs(unit_tree):
            all_earned, all_max = [], []
            for _, pair in unit_tree.iteritems():
                earned, max_ = pair
                if not (earned is None or max_ is None):
                    all_earned.append(float(earned))
                    all_max.append(float(max_))
            return all_earned, all_max

        def grade_subsection(subsection_tree):
            grades = []
            for unit_name, unit_pair in subsection_tree.iteritems():
                weight, unit_tree = unit_pair
                current_earned, current_max = get_unit_problem_pairs(unit_tree)
                if not enable_vertical:
                    weight = 1
                if weight and current_max:
                    grades.append(TestGrade(sum(current_earned), sum(current_max), weight))

            if enable_vertical:
                return grades
            subsection_grade = TestGrade(sum([x.earn for x in grades]), sum([x.max for x in grades]), 1)
            return [subsection_grade]

        def drop_minimal(grades_list):
            pc = [x.earn/x.max for x in grades_list]
            w = [x.weight for x in grades_list]
            ind = find_drop_index(pc, w)
            grades_list.pop(ind)

        def weighted_score(grades_list):
            percent = lambda x: x.earn/x.max if x.max else 0
            top = sum([percent(g)*g.weight for g in grades_list])
            bottom = sum([g.weight for g in grades_list])
            if not bottom:
                return 0
            return top/bottom

        score_by_assignment_category = {}
        for _, section_tree in tree.iteritems():
            for __, subsection_pair in section_tree.iteritems():
                assignment_category, subsection_tree = subsection_pair
                if not assignment_category:
                    continue
                if assignment_category not in score_by_assignment_category:
                    score_by_assignment_category[assignment_category] = []
                grades = grade_subsection(subsection_tree)
                score_by_assignment_category[assignment_category].extend(grades)

        course_score = 0
        assignment_category_meta = dict(
            ((x["type"], {"weight": x["weight"], "drop_count": x["drop_count"]})
             for x in self.course.grading_policy["GRADER"])
        )
        for assignment_category in score_by_assignment_category:
            drop_count = int(assignment_category_meta[assignment_category]["drop_count"])
            weight = assignment_category_meta[assignment_category]["weight"]

            for _ in range(drop_count):
                drop_minimal(score_by_assignment_category[assignment_category])
            assignment_score = weighted_score(score_by_assignment_category[assignment_category])
            course_score += assignment_score * weight

        course_score = round(course_score * 100 + 0.05) / 100
        return course_score

    def _enable_if_needed(self, enable_vertical):
        if enable_vertical:
            NpoedGradingFeatures.enable_vertical_grading(str(self.course.id))
            # needed in tests only
            self.course.vertical_grading = True
            #self.store.update_item(self.course, 0)
