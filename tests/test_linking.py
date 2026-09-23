"""Linking: bad input is rejected kindly, and every failure has a sentence."""

import unittest

from valstore import crypto
from valstore.bot.handlers import explain
from valstore.bot import texts
from valstore.errors import (
    AccountNotFound,
    AssetUnavailable,
    CloudflareBlock,
    LinkError,
    RateLimited,
    ReauthError,
    SessionDecryptError,
)
from valstore.linking.method import LinkMethodRegistry
from valstore.linking.sealed_paste import SealedPasteLinkMethod


class SealedPasteTest(unittest.TestCase):
    def setUp(self):
        self.private, self.public = crypto.generate_keypair()
        self.method = SealedPasteLinkMethod(self.private)

    def test_empty_and_garbage_input_raise_link_errors(self):
        for bad in ("", "   ", "/link", "not base64 at all!!"):
            with self.subTest(bad=bad):
                with self.assertRaises(LinkError):
                    self.method.complete(1, bad)

    def test_a_blob_sealed_to_another_key_is_refused(self):
        _other_private, other_public = crypto.generate_keypair()
        blob = crypto.seal(other_public, "ssid=abc")
        with self.assertRaises(LinkError):
            self.method.complete(1, blob)

    def test_a_valid_blob_without_a_session_cookie_is_refused(self):
        """It opened, but it isn't a Riot session — say so distinctly."""
        blob = crypto.seal(self.public, "this is not a cookie")
        with self.assertRaises(LinkError) as caught:
            self.method.complete(1, blob)
        self.assertIn("session cookie", str(caught.exception))

    def test_start_points_at_the_sealing_page(self):
        method = SealedPasteLinkMethod(self.private, "https://example.test/link/")
        challenge = method.start(1)
        self.assertIn("https://example.test/link/", challenge.instructions)
        # The terminal helper is still mentioned as the fallback.
        self.assertIn("seal_ssid.py", challenge.instructions)


class RegistryTest(unittest.TestCase):
    def test_single_method_is_offered_directly(self):
        registry = LinkMethodRegistry([SealedPasteLinkMethod("k")])
        self.assertIsNotNone(registry.only)

    def test_several_methods_require_a_choice(self):
        class _Other(SealedPasteLinkMethod):
            id = "other"

        registry = LinkMethodRegistry([SealedPasteLinkMethod("k"), _Other("k")])
        self.assertIsNone(registry.only)
        self.assertEqual(len(registry), 2)

    def test_unavailable_methods_are_hidden(self):
        class _Down(SealedPasteLinkMethod):
            id = "down"

            @property
            def available(self):
                return False

        registry = LinkMethodRegistry([_Down("k")])
        self.assertEqual(len(registry), 0)
        self.assertIsNone(registry.get("down"))


class ExplainTest(unittest.TestCase):
    """Users get an instruction, never a traceback."""

    def test_each_failure_maps_to_its_own_advice(self):
        cases = {
            SessionDecryptError("x"): texts.ERR_SESSION_UNREADABLE,
            CloudflareBlock("x"): texts.ERR_CLOUDFLARE,
            ReauthError("x"): texts.ERR_SESSION_EXPIRED,
            AssetUnavailable("x"): texts.ERR_CATALOG,
            AccountNotFound("x"): texts.ERR_NO_SUCH_ACCOUNT,
        }
        for error, expected in cases.items():
            with self.subTest(error=type(error).__name__):
                self.assertEqual(explain(error), expected)

    def test_cloudflare_beats_its_reauth_parent(self):
        """CloudflareBlock subclasses ReauthError; the advice must differ."""
        self.assertNotEqual(explain(CloudflareBlock("x")),
                            explain(ReauthError("x")))

    def test_link_errors_speak_for_themselves(self):
        self.assertEqual(explain(LinkError("Re-run the helper.")),
                         "Re-run the helper.")

    def test_rate_limit_reports_minutes(self):
        self.assertIn("10", explain(RateLimited(600)))

    def test_an_unexpected_error_leaks_nothing(self):
        message = explain(ValueError("ssid=SUPERSECRET leaked here"))
        self.assertEqual(message, texts.ERR_UNEXPECTED)
        self.assertNotIn("SUPERSECRET", message)
