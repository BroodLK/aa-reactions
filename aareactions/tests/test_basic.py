"""
Reactions Test
"""

# Django
from django.test import TestCase


class TestBasic(TestCase):
    """
    TestBasic
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        Test setup
        :return:
        :rtype:
        """

        super().setUpClass()

    def test_basic(self):
        """
        Dummy test function
        :return:
        :rtype:
        """

        self.assertEqual(True, True)
