import ddt
from mock import patch
from django.conf import settings
from openedx.core.djangolib.testing.utils import get_mock_request

from lms.djangoapps.grades.new.course_grade_factory import CourseGradeFactory, CourseData
from lms.djangoapps.grades.tests.utils import answer_problem

from student.models import CourseEnrollment
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase, SharedModuleStoreTestCase

from .test_utils import BuildCourseMixin, ContentGroupsMixin


@patch.dict(settings.FEATURES, {'PERSISTENT_GRADES_ENABLED_FOR_ALL_TESTS': False})
class TestExpectedGrading(ModuleStoreTestCase, BuildCourseMixin):
    """
    Check that our testing method in BuildCourseMixin correctly calculates grade
    for course represented by tree.
    This test class uses a hard-coded block
    hierarchy with scores as follows:
                                                a
                                       +--------+--------+
                                       b                 c
                        +--------------+-----------+     |
                        d 5            e 1         f     g 10
                     +-----+     +-----+-----+     |     |
                     h     i     j     k     l     m     n
                   (2/5) (3/5) (0/1)   -   (1/3)   -   (6/10)

    """
    def setUp(self):
        super(TestExpectedGrading, self).setUp()
        self.course = CourseFactory.create()
        with self.store.bulk_operations(self.course.id):
            self.a = ItemFactory.create(parent=self.course, category="chapter", display_name="a")
            metadata = {'format':'Homework', 'graded':True}
            self.b = ItemFactory.create(parent=self.a, category="sequential", display_name="b", metadata=metadata)
            self.c = ItemFactory.create(parent=self.a, category="sequential", display_name="c", metadata=metadata)
            self.d = ItemFactory.create(parent=self.b, category="vertical", display_name="d")
            self.e = ItemFactory.create(parent=self.b, category="vertical", display_name="e")
            self.f = ItemFactory.create(parent=self.b, category="vertical", display_name="f")
            self.g = ItemFactory.create(parent=self.c, category="vertical", display_name="g")
            metadata.pop('graded')
            self.h = ItemFactory.create(parent=self.d, category="problem", display_name="h", metadata=metadata)
            self.i = ItemFactory.create(parent=self.d, category="problem", display_name="i", metadata=metadata)
            self.j = ItemFactory.create(parent=self.e, category="problem", display_name="j", metadata=metadata)
            self.k = ItemFactory.create(parent=self.e, category="html", display_name="k")
            self.l = ItemFactory.create(parent=self.e, category="problem", display_name="l", metadata=metadata)
            self.m = ItemFactory.create(parent=self.f, category="html", display_name="m")
            self.n = ItemFactory.create(parent=self.g, category="problem", display_name="n", metadata=metadata)

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

        self.request = get_mock_request(UserFactory())
        CourseEnrollment.enroll(self.request.user, self.course.id)

        answer_problem(self.course, self.request, self.h, score=2, max_value=5)
        answer_problem(self.course, self.request, self.i, score=3, max_value=5)
        answer_problem(self.course, self.request, self.j, score=0, max_value=1)
        answer_problem(self.course, self.request, self.l, score=1, max_value=3)
        answer_problem(self.course, self.request, self.n, score=6, max_value=10)

    def test_percents_coincide(self):
        """
        Checks that grade returned by .grade_tree method and manually calculated
        one are equal.
        """
        course_grade = CourseGradeFactory().create(self.request.user, self.course)
        pc = course_grade.percent
        subsection_grades = [
            (2. + 3. + 0. + 1.) / (5. + 5. + 1. + 3.),
            6./10
        ]
        expected_grade = sum(subsection_grades)/len(subsection_grades)
        expected_pc = round(expected_grade * 100 + 0.05) / 100
        self.assertEqual(pc, expected_pc)
        tree = {
            "a": {
                "b": ("Homework", {
                    "d": (1., {"h": (2., 5.), "i": (3., 5.),}),
                    "e": (1., {"j": (0., 1.), "k": (None, None), "l":(1.,3)}),
                    "f": (1., {"m":(None, None)})
                }),
                "c": ("Homework", {
                    "g": (1, {"n": (6., 10)})
                })
            }
        }
        model_calculated_pc = self._grade_tree(tree, enable_vertical=False)
        self.assertEqual(pc, model_calculated_pc)

@patch.dict(settings.FEATURES, {'PERSISTENT_GRADES_ENABLED_FOR_ALL_TESTS': False})
@ddt.ddt
class TestCourseBuilding(ModuleStoreTestCase, BuildCourseMixin):
    """
    Tests that our testing method in BuildCourseMixin builds course correctly from
    tree, and calculated grades are correct for both Vertical and classical grading
                                                a
                                       +--------+--------+
                                       b                 c
                        +--------------+-----------+     |
                        d 5            e 1         f     g 10
                     +-----+     +-----+-----+     |     |
                     h     i     j     k     l     m     n
                   (2/5) (3/5) (0/1)   -   (1/3)   -   (6/10)

    """
    def setUp(self):
        super(TestCourseBuilding, self).setUp()
        self.course = CourseFactory.create()
        self.request = get_mock_request(UserFactory())
        self._update_grading_policy()
        CourseEnrollment.enroll(self.request.user, self.course.id)

    @ddt.data(False, True)
    def test_percent(self, enable_vertical):
        tree = {
            "a": {
                "b": ("Homework", {
                    "d": (0., {"h": (2., 5.), "i": (3., 5.),}),
                    "e": (1., {"j": (0., 1.), "k": (None, None), "l":(1.,3)}),
                    "f": (0., {"m": (None, None)})
                }),
                "c": ("Homework", {
                    "g": (0, {"n": (6., 10)})
                })
            }
        }
        self._build_from_tree(tree)
        self._enable_if_needed(enable_vertical)

        self._check_tree(tree, self.course)
        course_grade = CourseGradeFactory().create(self.request.user, self.course)
        pc = course_grade.percent

        subsection_grades = [
            (2. + 3. + 0. + 1.) / (5. + 5. + 1. + 3.),
            6./10
        ]
        expected_grade = sum(subsection_grades)/len(subsection_grades)
        if enable_vertical:
            expected_grade = 0.25
        expected_pc = round(expected_grade * 100 + 0.05) / 100
        self.assertEqual(pc, expected_pc)
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)


@patch.dict(settings.FEATURES, {'PERSISTENT_GRADES_ENABLED_FOR_ALL_TESTS': False})
@ddt.ddt
class TestVerticalGrading(ModuleStoreTestCase, BuildCourseMixin, ContentGroupsMixin):
    """
    Tests different states and courses represented by tree
    """

    def setUp(self):
        super(TestVerticalGrading, self).setUp()
        self.course = CourseFactory.create()
        self.request = get_mock_request(UserFactory())
        self._update_grading_policy()
        CourseEnrollment.enroll(self.request.user, self.course.id)

    @ddt.data(True, False)
    def test_simple(self, enable_vertical):
        """
        Test some simple course
        """
        tree = {
            "a": {
                "b": ("Homework", {
                    "c": (2., {"d": (0., 1.), "e": (1., 1.)}),
                }),
            }
        }
        self._update_grading_policy()
        self._build_from_tree(tree)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)
        pc = CourseGradeFactory().create(self.request.user, self.course).percent
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)
        self.assertEqual(pc, 0.5)

    @ddt.data(True, False)
    def test_unanswered(self, enable_vertical):
        """
        Test that course grade at start is 0
        """
        tree = {
            "a": {
                "b": ("Homework", {
                    "c": (2., {"d": (0, 1.), "e": (0, 1.)}),
                }),
            }
        }
        self._update_grading_policy()
        self._build_from_tree(tree)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)
        pc = CourseGradeFactory().create(self.request.user, self.course).percent
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)
        expected_pc = 0.0
        self.assertEqual(pc, expected_pc)

    @ddt.data(True, False)
    def test_no_graded_subsections(self, enable_vertical):
        """
        Test that course grade where nothing is graded
        """
        tree = {
            "a": {
                "b": (None, {
                    "c": (1., {"d": (0, 1.), "e": (0, 1.)}),
                }),
            }
        }
        self._update_grading_policy()
        self._build_from_tree(tree)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)
        pc = CourseGradeFactory().create(self.request.user, self.course).percent
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)
        self.assertEqual(pc, 0.0)

    @ddt.data(True, False)
    def test_has_zero_weights(self, enable_vertical):
        """
        Test that course grade at start is 0
        """
        tree = {
            "a": {
                "b": ("Homework", {
                    "c": (1., {"d": (0., 1.), "e": (0., 1.)}),
                    "f": (0., {"g": (0., 1.), "h": (1., 1.)}),
                    "i": (4., {"j": (1., 1.), "k": (1., 1.)}),

                }),
            }
        }
        self._update_grading_policy()
        self._build_from_tree(tree)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)
        # TODO: somehow .create doesn't work. Why?
        # pc = CourseGradeFactory().create(self.request.user, self.course).percent
        pc = CourseGradeFactory().create(self.request.user, self.course).percent

        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)
        expected_pc = 0.8 if enable_vertical else 0.5
        self.assertEqual(pc, expected_pc)

    @ddt.data(True, False)
    def test_several_subsections(self, enable_vertical):
        """
        Test with several subsections, both graded and not
        """
        tree = {
            "a": {
                "b": ("Homework", {
                    "c": (1., {"d": (0., 1.), "e": (0., 1.)}),

                }),
                "f": ("", {
                    "g": (1., {"h": (1., 1.), "i": (1., 1.)}),
                }),
                "j": ("Homework", {
                    "l": (1., {"m":(1,1)}),
                    "n": (0., {"o":(1,1)})
                })
            }
        }
        self._update_grading_policy()
        self._build_from_tree(tree)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)

        pc = CourseGradeFactory().create(self.request.user, self.course).percent
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)

        expected_pc = 0.5
        self.assertEqual(pc, expected_pc)

    @ddt.data(True, False)
    def test_several_assignment_categories(self, enable_vertical):
        """
        Test with two assignments: Homework and Exam
        """
        #
        tree = {
            "a": {
                "b": ("Homework", {
                    "c": (1., {"d": (0., 1.), "e": (1., 1.)}),
                    "c2":(0., {"d2":(0., 1.), "e2":(1., 1.)}),
                }),
                "f": ("Exam", {
                    "g": (1., {"h": (1., 1.), "i": (1., 1.)}),
                    "j": (3., {"k": (0., 1.), "l": (1., 1.)})
                }),
            }
        }
        grading_policy = {
            "GRADER": [
                {
                    "type": "Homework",
                    "min_count": 1,
                    "drop_count": 0,
                    "short_label": "HW",
                    "weight": 0.4,
                },
                {
                    "type": "Exam",
                    "min_count": 1,
                    "drop_count": 0,
                    "short_label": "Exam",
                    "weight": 0.6,
                },
            ],
            "GRADE_CUTOFFS": {
                "Pass": 0.5,
            },
        }
        self._build_from_tree(tree)
        self._update_grading_policy(grading_policy)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)

        # TODO: somehow .create doesn't work. Why?
        # pc = CourseGradeFactory().create(self.request.user, self.course).percent
        pc = CourseGradeFactory().create(self.request.user, self.course).percent

        expected_pc_vertical = 0.4*((1.*.5 + 0.*.5)/1) + 0.6*((1.*1 + .5*3)/4)
        expected_pc_non_vertical = 0.4*.5 + 0.6*0.75
        expected_pc = expected_pc_vertical if enable_vertical else expected_pc_non_vertical
        self.assertEqual(pc, round(expected_pc + 0.05/100, 2)) # edx grade rounding, fails otherwise

        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)

    @ddt.data(True, False)
    def test_droppable_subsections(self, enable_vertical):
        """
        Tests subsection drop with low score works
        """
        tree = {
            "a": {
                "b1": ("Homework", {  # NW 0.5;
                    "c1": (1., {"d1": (0., 1.), "e1": (0., 1.)}), # W:0.
                    "f1": (4., {"g1": (1., 1.), "h1": (1., 1.)}), # W:1.
                }),
                "b2": ("Homework", { # NW 0.75
                    "c2": (1., {"d2": (1., 1.), "e2": (1., 1.)}), # W:1.
                    "f2": (4., {"g2": (1., 1.), "h2": (0., 1.)}), # W:0.5
                }),
                "b3": ("Homework", { # NW 0.25;
                    "c3": (1., {"d3": (0., 1.), "e3": (1., 1.)}), # W:0.5
                    "f3": (4., {"g3": (0., 1.), "h3": (0., 1.)}), # W:0.
                }),
            }
        }
        DROP_COUNT = 2
        grading_policy = {
            "GRADER": [
                {
                    "type": "Homework",
                    "min_count": 1,
                    "drop_count": DROP_COUNT,
                    "short_label": "HW",
                    "weight": 1.,
                },
            ],
            "GRADE_CUTOFFS": {
                "Pass": 0.5,
            },
        }

        self._build_from_tree(tree)
        self._update_grading_policy(grading_policy)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)

        pc = CourseGradeFactory().create(self.request.user, self.course).percent

        #checked all drop index - the best is [1, 1, 1, 0, 1, 0]
        drop = [1, 1, 1, 0, 1, 0]
        weight = [1, 4, 1, 4, 1, 4]
        gpc = [0, 1, 1, 0.5, 0.5, 0]
        expected_pc_vertical = sum([drop[n]*weight[n]*gpc[n] for n in range(len(gpc))])
        expected_pc_vertical /=sum([drop[n]*weight[n]       for n in range(len(gpc))])
        expected_pc_non_vertical = 0.75
        expected_pc = expected_pc_vertical if enable_vertical else expected_pc_non_vertical
        self.assertEqual(pc, round(expected_pc + 0.05 / 100, 2))

        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)

    @ddt.data(True, False)
    def test_drop_last_element(self, enable_vertical):
        """
        Tests that when we drop everything from the course by grading_policy,
        course grade is 0
        """
        tree = {
            "a": {
                "b1": ("Homework", {  # NW 0.5; W: 0.8
                    "c1": (1., {"d1": (1., 1.), "e1": (0., 1.)}),  # W:0/1
                }),
            }
        }
        DROP_COUNT = 1
        grading_policy = {
            "GRADER": [
                {
                    "type": "Homework",
                    "min_count": 0,
                    "drop_count": DROP_COUNT,
                    "short_label": "HW",
                    "weight": 1.,
                },
            ],
            "GRADE_CUTOFFS": {
                "Pass": 0.5,
            },
        }

        self._build_from_tree(tree)
        self._update_grading_policy(grading_policy)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)

        pc = CourseGradeFactory().create(self.request.user, self.course).percent
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)
        self.assertEqual(pc, 0)

    @ddt.data(True, False)
    def test_drop_last_element_with_several_ss(self, enable_vertical):
        """
        Tests that when we drop last value from subsection in vertical grading, it improves the
        gain
        """
        tree = {
            "a": {
                "b1": ("Homework", {
                    "c1": (1., {"d1": (1., 1.), "e1": (0., 1.)}),
                }),
                "b2": ("Homework", {
                    "c2": (1., {"d2": (1., 1.), "e2": (0., 1.)}),
                }),

            }
        }
        DROP_COUNT = 1
        grading_policy = {
            "GRADER": [
                {
                    "type": "Homework",
                    "min_count": 0,
                    "drop_count": DROP_COUNT,
                    "short_label": "HW",
                    "weight": 1.,
                },
            ],
            "GRADE_CUTOFFS": {
                "Pass": 0.5,
            },
        }

        self._build_from_tree(tree)
        self._update_grading_policy(grading_policy)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)

        pc = CourseGradeFactory().create(self.request.user, self.course).percent
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)

        self.assertEqual(pc, 0.5)

    @ddt.data(True, False)
    def test_drop_optimal(self, enable_vertical):
        """
        Tests that unit drops chooses optimal solution:
        We should drop c4, because we'll get (1 + 0)/(1+1) against
        (1 + 1) / (1 + 4) if drop c3 instead
        """
        tree = {
            "a": {
                "b1": ("Homework", { #NW 0.5; W: 0.5
                    "c1": (1., {"d1": (1., 1.), "e1": (1., 1.)}), #W: 0.5/1
                }),
                "b2": ("Homework", { #NW 0.5; W: 0.5
                    "c2": (1., {"d2": (1., 1.), "e2": (1., 1.)}), #W 1/1
                    "c3": (1., {"d3": (0., 1.)}), # 0/1
                    "c4": (4., {"d4": (1., 1.), "e41": (0., 1.), "e42": (0., 1.), "e43": (0., 1.) }),
                }),
            }
        }
        DROP_COUNT = 1
        grading_policy = {
            "GRADER": [
                {
                    "type": "Homework",
                    "min_count": 0,
                    "drop_count": DROP_COUNT,
                    "short_label": "HW",
                    "weight": 1.,
                },
            ],
            "GRADE_CUTOFFS": {
                "Pass": 0.5,
            },
        }
        self._build_from_tree(tree)
        self._update_grading_policy(grading_policy)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)
        pc = CourseGradeFactory().create(self.request.user, self.course).percent
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)
        #drop with weight 4
        grade_round = lambda x: round(x + 0.05 / 100, 2)
        expected_pc = grade_round ((1.*1 + 1*1 + 0*1)/(1+1+1)) if enable_vertical else 1
        self.assertEqual(pc, expected_pc)

    @ddt.data(True, False)
    def test_drop_over_min_count(self, enable_vertical):
        """
        Tests that when we have mincount > 0 we still drop worst element
        """
        tree = {
            "a": {
                "b1": ("Homework", {
                    "c1": (1., {"d1": (0., 1.), "e1": (1., 1.)}),
                }),
            }
        }
        DROP_COUNT = 1
        MIN_COUNT = 1
        grading_policy = {
            "GRADER": [
                {
                    "type": "Homework",
                    "min_count": MIN_COUNT,
                    "drop_count": DROP_COUNT,
                    "short_label": "HW",
                    "weight": 1.,
                },
            ],
            "GRADE_CUTOFFS": {
                "Pass": 0.5,
            },
        }
        self._update_grading_policy(grading_policy)
        self._build_from_tree(tree)
        self._enable_if_needed(enable_vertical)
        self._check_tree(tree, self.course)
        pc = CourseGradeFactory().create(self.request.user, self.course).percent
        model_calculated_pc = self._grade_tree(tree, enable_vertical)
        self.assertEqual(pc, model_calculated_pc)
        expected_pc = 0.
        self.assertEqual(pc, expected_pc)