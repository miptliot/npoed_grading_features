import json
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import models
from opaque_keys.edx.keys import CourseKey


class NpoedGradingFeatures(models.Model):
    """
    Defines for which courses which npoed grading features are enabled.
    """
    course_id = models.CharField(max_length=255, unique=True)
    vertical_grading = models.BooleanField(default=False)
    passing_grade = models.BooleanField(default=False)
    problem_best_score = models.BooleanField(default=False)

    KEY_BASE = "NpoedGradingFeatures.{course_id}"
    TIMEOUT = 300

    @classmethod
    def is_vertical_grading_enabled(cls, course_id):
        return cls._is_feature_enabled(course_id, 'vertical_grading')

    @classmethod
    def is_passing_grade_enabled(cls, course_id):
        return cls._is_feature_enabled(course_id, 'passing_grade')

    @classmethod
    def is_problem_best_score_enabled(cls, course_id):
        return cls._is_feature_enabled(course_id, 'problem_best_score')

    @classmethod
    def enable_vertical_grading(cls, course_id):
        cls._switch_feature(course_id, "vertical_grading", True)

    @classmethod
    def enable_passing_grade(cls, course_id):
        cls._switch_feature(course_id, "passing_grade", True)

    @classmethod
    def enable_problem_best_score_grade(cls, course_id):
        cls._switch_feature(course_id, "problem_best_score", True)

    @classmethod
    def disable_vertical_grading(cls, course_id):
        cls._switch_feature(course_id, "vertical_grading", False)

    @classmethod
    def disable_passing_grade(cls, course_id):
        cls._switch_feature(course_id, "passing_grade", False)

    @classmethod
    def disable_problem_best_score_grade(cls, course_id):
        cls._switch_feature(course_id, "problem_best_score", False)

    @classmethod
    def get(cls, course_id, allow_cached=False):
        cid = cls._get_id(course_id)
        if allow_cached:
            value = cls._get_cache(cid)
            if value:
                return value
        try:
            value = cls.objects.get(course_id=cid)
            value._set_cache()
            return value
        except cls.DoesNotExist:
            return None

    @classmethod
    def _get_id(cls, course_id):
        if isinstance(course_id, CourseKey):
            return str(course_id)
        return course_id

    @classmethod
    def _is_feature_enabled(cls, course_id, feature):
        cid = cls._get_id(course_id)
        grading_features = cls.get(course_id=cid, allow_cached=True)
        if grading_features:
            return getattr(grading_features, feature)
        else:
            return False

    @classmethod
    def _switch_feature(cls, course_id, feature, state):
        cid = cls._get_id(course_id)
        grading_features, created = cls.objects.get_or_create(course_id=cid)
        setattr(grading_features, feature, state)
        grading_features.save()

    def _to_json(self):
        return json.dumps({
            "course_id": self.course_id,
            "passing_grade": self.passing_grade,
            "vertical_grading": self.vertical_grading,
            "problem_best_score": self.problem_best_score
        })

    @classmethod
    def _from_json(cls, data):
        return cls(**json.loads(data))

    def _set_cache(self):
        key = self.KEY_BASE.format(course_id=str(self.course_id))
        cache.set(key, self._to_json(), self.TIMEOUT)

    @classmethod
    def _get_cache(cls, course_id):
        key = cls.KEY_BASE.format(course_id=str(course_id))
        data = cache.get(key)
        if data:
            return cls._from_json(data)

    def save(self, *args, **kwargs):
        super(NpoedGradingFeatures, self).save(*args, **kwargs)
        self._set_cache()

    def __str__(self):
        return "NGF<{}>({}/{}/{})".format(self.course_id, int(self.passing_grade), int(self.problem_best_score), int(self.vertical_grading))


class CoursePassingGradeUserStatus(models.Model):
    """
    Stores course passing grade results for student. Results are
    stored as a json-ized list of messages where is specified which
    passing grades are failed by user. These messages are shown at
    progress page as unmet requirements.
    """
    course_id = models.CharField(max_length=255)
    user = models.ForeignKey(User)
    fail_status_messages = models.TextField(
        verbose_name="Message that specifies what user has to do to pass"
    )

    class Meta:
        unique_together = ("course_id", "user")

    @classmethod
    def get_passing_grade_status(cls, course_key, user):
        course_id = str(course_key)
        if not NpoedGradingFeatures.is_passing_grade_enabled(course_id):
            raise ValueError("Passing grade is not enabled for course {}.".format(
                course_id
            ))
        try:
            row = cls.objects.get(course_id=course_id, user=user)
            messages = json.loads(row.fail_status_messages)
        except cls.DoesNotExist:
            messages = tuple("You progress is not processed yet")
        return messages

    @classmethod
    def set_passing_grade_status(cls, course_key, user, fail_status_messages):
        course_id = str(course_key)
        if not NpoedGradingFeatures.is_passing_grade_enabled(course_id):
            raise ValueError("Passing grade is not enabled for course {}.".format(
                course_id
            ))
        row, created = cls.objects.get_or_create(course_id=course_id, user=user)
        row.fail_status_messages = json.dumps(fail_status_messages)
        row.save()
