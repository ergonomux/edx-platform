from contextlib import contextmanager
from datetime import datetime, timedelta
import itertools
from unittest import TestCase

import ddt
from freezegun import freeze_time
import pytz
import waffle

from course_modes.models import CourseMode
from openedx.core.djangoapps.certificates import api
from openedx.core.djangoapps.certificates.config import waffle as certs_waffle
from openedx.core.djangoapps.content.course_overviews.tests.factories import CourseOverviewFactory
from student.tests.factories import CourseEnrollmentFactory, UserFactory


# TODO: Copied from lms.djangoapps.certificates.models,
# to be resolved per https://openedx.atlassian.net/browse/EDUCATOR-1318
class CertificateStatuses(object):
    """
    Enum for certificate statuses
    """
    deleted = 'deleted'
    deleting = 'deleting'
    downloadable = 'downloadable'
    error = 'error'
    generating = 'generating'
    notpassing = 'notpassing'
    restricted = 'restricted'
    unavailable = 'unavailable'
    auditing = 'auditing'
    audit_passing = 'audit_passing'
    audit_notpassing = 'audit_notpassing'
    unverified = 'unverified'
    invalidated = 'invalidated'
    requesting = 'requesting'

    ALL_STATUSES = (
        deleted, deleting, downloadable, error, generating, notpassing, restricted, unavailable, auditing,
        audit_passing, audit_notpassing, unverified, invalidated, requesting
    )


class MockGeneratedCertificate(object):
    """
    We can't import GeneratedCertificate from LMS here, so we roll
    our own minimal Certificate model for testing.
    """
    def __init__(self, user=None, course_id=None, mode=None, status=None):
        self.user = user
        self.course_id = course_id
        self.mode = mode
        self.status = status

    def is_valid(self):
        """
        Return True if certificate is valid else return False.
        """
        return self.status == CertificateStatuses.downloadable


def days(n):
    return timedelta(days=n)


@contextmanager
def configure_waffle_namespace(feature_enabled):
    namespace = certs_waffle.waffle()

    with namespace.override(certs_waffle.AUTO_CERTIFICATE_GENERATION, active=feature_enabled):
        yield


class CertificatesApiBaseTestCase(TestCase):
    def setUp(self):
        super(CertificatesApiBaseTestCase, self).setUp()
        self.course = CourseOverviewFactory.create(
            start=datetime(2017, 1, 1, tzinfo=pytz.UTC),
            end=datetime(2017, 1, 31, tzinfo=pytz.UTC),
            certificate_available_date=None
        )

    def tearDown(self):
        super(CertificatesApiBaseTestCase, self).tearDown()
        self.course.self_paced = False
        self.course.certificate_available_date = None
        self.course.certificates_display_behavior = 'end'
        self.course.certificates_show_early = False
        self.course.save()


@ddt.ddt
class VisibilityTestCase(CertificatesApiBaseTestCase):
    def setUp(self):
        super(VisibilityTestCase, self).setUp()
        self.user = UserFactory.create()
        self.enrollment = CourseEnrollmentFactory(
            user=self.user,
            course_id=self.course.id,
            is_active=True,
            mode='audit',
        )
        self.certificate = MockGeneratedCertificate(
            user=self.user,
            course_id=self.course.id
        )

    @ddt.data(True, False)
    def test_auto_certificate_generation_enabled(self, feature_enabled):
        with configure_waffle_namespace(feature_enabled):
            self.assertEqual(feature_enabled, api.auto_certificate_generation_enabled())

    @ddt.data(
        (True, True, False),  # feature enabled and self-paced should return False
        (True, False, True),  # feature enabled and instructor-paced should return True
        (False, True, False),  # feature not enabled and self-paced should return False
        (False, False, False),  # feature not enabled and instructor-paced should return False
    )
    @ddt.unpack
    def test_can_show_certificate_available_date_field(
            self, feature_enabled, is_self_paced, expected_value
    ):
        self.course.self_paced = is_self_paced
        with configure_waffle_namespace(feature_enabled):
            self.assertEqual(expected_value, api.can_show_certificate_available_date_field(self.course))

    @ddt.data(
        (CourseMode.CREDIT_MODE, True, True),
        (CourseMode.VERIFIED, True, True),
        (CourseMode.AUDIT, True, False),
        (CourseMode.CREDIT_MODE, False, True),
        (CourseMode.VERIFIED, False, True),
        (CourseMode.AUDIT, False, False),
    )
    @ddt.unpack
    def test_can_show_view_certificate_button_self_paced(
            self, enrollment_mode, feature_enabled, expected_value_if_downloadable
    ):
        self.enrollment.mode = enrollment_mode
        self.enrollment.save()

        self.course.self_paced = True
        self.course.save()

        for certificate_status in CertificateStatuses.ALL_STATUSES:
            self.certificate.mode = enrollment_mode
            self.certificate.status = certificate_status

            expected_to_view = (
                expected_value_if_downloadable and
                (certificate_status == CertificateStatuses.downloadable)
            )
            with configure_waffle_namespace(feature_enabled):
                self.assertEquals(expected_to_view, api.can_show_view_certificate_button(self.course, self.certificate))

    @ddt.data(
        # feature is enabled, course ended, null certificate_available_date
        (CourseMode.CREDIT_MODE, True, None, days(1), True),
        (CourseMode.VERIFIED, True, None, days(1), True),
        (CourseMode.AUDIT, True, None, days(1), False),

        # feature enabled, course ended, cert date in past
        (CourseMode.CREDIT_MODE, True, days(1), days(2), True),
        (CourseMode.VERIFIED, True, days(1), days(2), True),
        (CourseMode.AUDIT, True, days(1), days(2), False),

        # feature enabled, course ended, cert date in future
        (CourseMode.CREDIT_MODE, True, days(2), days(1), False),
        (CourseMode.VERIFIED, True, days(2), days(1), False),
        (CourseMode.AUDIT, True, days(2), days(1), False),

        # feature not enabled, so only depend on course having ended
        (CourseMode.CREDIT_MODE, False, None, days(1), True),
        (CourseMode.VERIFIED, False, None, days(1), True),
        (CourseMode.AUDIT, False, None, days(1), False),
    )
    @ddt.unpack
    def test_can_show_view_certificate_button_instructor_paced(
            self, enrollment_mode, feature_enabled, cert_avail_delta, current_time_delta, expected_value_if_downloadable
    ):
        self.enrollment.mode = enrollment_mode
        self.enrollment.save()

        self.course.self_paced = False
        if cert_avail_delta:
            self.course.certificate_available_date = self.course.end + cert_avail_delta
        self.course.save()

        for certificate_status in CertificateStatuses.ALL_STATUSES:
            self.certificate.mode = enrollment_mode
            self.certificate.status = certificate_status

            expected_to_view = (
                expected_value_if_downloadable and
                (certificate_status == CertificateStatuses.downloadable)
            )
            with configure_waffle_namespace(feature_enabled):
                with freeze_time(self.course.end + current_time_delta):
                    self.assertEquals(
                        expected_to_view,
                        api.can_show_view_certificate_button(self.course, self.certificate)
                    )

    @ddt.data(
        (True, 'early_with_info', True),
        (True, 'end', True),
        (False, 'early_no_info', True),
        (False, 'end', False),
    )
    @ddt.unpack
    def test_can_show_view_certificate_button_advanced_settings(
            self, show_before_end, display_behavior, expected_value
    ):
        """
        When the feature is enabled, and it's an instructor-paced course, verified learners
        should be able to view the "View Certificate" button when an advanced setting
        dictates that certificates are available "early", as long as the certificate
        status is "downloadable".
        """
        self.enrollment.mode = CourseMode.VERIFIED
        self.enrollment.save()

        self.course.self_paced = False
        self.course.certificates_show_before_end = show_before_end
        self.course.certificates_display_behavior = display_behavior
        self.course.save()

        self.certificate.mode = CourseMode.VERIFIED
        self.certificate.status = CertificateStatuses.downloadable

        with configure_waffle_namespace(True):
            # make it so that the course has not yet ended.
            with freeze_time(self.course.end - days(1)):
                self.assertEquals(expected_value, api.can_show_view_certificate_button(self.course, self.certificate))

    @ddt.data((days(-1), False), (days(1), True))
    @ddt.unpack
    def test_can_show_view_certificate_button_course_ended(self, current_time_delta, expected_value):
        """
        When the feature is enabled in an instructor-paced course, but no
        advanced setting is configured to show certs early, and the
        certificate_available_date is null, the button should be visible
        when the course has ended, and not visible otherwise.
        """
        self.enrollment.mode = CourseMode.VERIFIED
        self.enrollment.save()

        self.course.self_paced = False
        self.course.certificates_show_before_end = False
        self.course.certificates_display_behavior = 'end'
        self.course.save()

        self.certificate.mode = CourseMode.VERIFIED
        self.certificate.status = CertificateStatuses.downloadable

        with configure_waffle_namespace(True):
            with freeze_time(self.course.end + current_time_delta):
                self.assertEquals(expected_value, api.can_show_view_certificate_button(self.course, self.certificate))
