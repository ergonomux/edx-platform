"""
The public API for certificates.
"""
from datetime import datetime

from pytz import UTC

from course_modes.models import CourseMode
from openedx.core.djangoapps.certificates.config import waffle
from student.models import CourseEnrollment


SWITCHES = waffle.waffle()

# Copied from lms.djangoapps.certificates.models.GeneratedCertificate,
# to be resolved per https://openedx.atlassian.net/browse/EDUCATOR-1318
VERIFIED_CERTS_MODES = [CourseMode.VERIFIED, CourseMode.CREDIT_MODE]


def auto_certificate_generation_enabled():
    return SWITCHES.is_enabled(waffle.AUTO_CERTIFICATE_GENERATION)


def _enabled_and_instructor_paced(course):
    if auto_certificate_generation_enabled():
        return not course.self_paced
    return False


def certificates_viewable_for_course(course):
    """
    Returns True if certificates are viewable for any student enrolled in the course, False otherwise.
    """
    if course.self_paced:
        return True
    if (
        course.certificates_display_behavior in ('early_with_info', 'early_no_info')
        or course.certificates_show_before_end
    ):
        return True
    if (
        course.certificate_available_date
        and course.certificate_available_date <= datetime.now(UTC)
    ):
        return True
    if (
        course.certificate_available_date is None
        and course.has_ended()
    ):
        return True
    return False


def enrollment_is_verified(student, course_id):
    """
    Returns True if the student has a verified certificate enrollment in the course, False otherwise.
    """
    enrollment_mode, __ = CourseEnrollment.enrollment_mode_for_user(student, course_id)
    return enrollment_mode in VERIFIED_CERTS_MODES


def enrollment_is_active(student, course_id):
    return CourseEnrollment.enrollment_mode_for_user(student, course_id)[1]


def is_certificate_valid(certificate):
    """
    Returns True if the student has a valid, verified certificate for this course, False otherwise.
    """
    return enrollment_is_verified(certificate.user, certificate.course_id) and certificate.is_valid()


def can_show_view_certificate_button(course, certificate):
    """
    Returns True if the student with the given certificate can see the
    "View Certificate" button on their course progress page, False otherwise.
    """
    if not certificate:
        return False

    certificate_is_valid = is_certificate_valid(certificate)
    if auto_certificate_generation_enabled():
        return certificates_viewable_for_course(course) and certificate_is_valid
    return certificate_is_valid


def can_show_certificate_message(course, student):
    return (
        enrollment_is_active(student, course.id) and
        certificates_viewable_for_course(course)
    )


def is_course_passed(course, grade_summary):
    nonzero_cutoffs = [cutoff for cutoff in course.grade_cutoffs.values() if cutoff > 0]
    success_cutoff = min(nonzero_cutoffs) if nonzero_cutoffs else None
    return success_cutoff and grade_summary['percent'] >= success_cutoff


def can_show_certificate_available_date_field(course):
    return _enabled_and_instructor_paced(course)


def display_date_for_certificate(course, certificate):
    if (
        auto_certificate_generation_enabled() and
        not course.self_paced and
        course.certificate_available_date and
        course.certificate_available_date < datetime.now(UTC)
    ):
        return course.certificate_available_date

    return certificate.modified_date
